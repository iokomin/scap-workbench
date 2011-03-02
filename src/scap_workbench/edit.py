# -*- coding: utf-8 -*-
#
# Copyright 2010 Red Hat Inc., Durham, North Carolina.
# All Rights Reserved.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Authors:
#      Maros Barabas        <mbarabas@redhat.com>
#      Vladimir Oberreiter  <xoberr01@stud.fit.vutbr.cz>

import pygtk
import gtk
import gobject
import pango
import datetime
import time
import re

import abstract
import logging
import core
from events import EventObject
logger = logging.getLogger("scap-workbench")
try:
    import openscap_api as openscap
except Exception as ex:
    logger.error("OpenScap library initialization failed: %s", ex)
    openscap=None
    
import commands
import filter
import render

logger = logging.getLogger("scap-workbench")
    
from htmltextview import HtmlTextView
from threads import thread as threadSave

class ProfileList(abstract.List):
    
    def __init__(self, widget, core, builder=None, progress=None, filter=None):
        self.core = core
        self.builder = builder
        self.data_model = commands.DHProfiles(core)
        abstract.List.__init__(self, "gui:edit:profile_list", core, widget)

        # Popup Menu
        self.builder.get_object("edit:profile_list:popup:add").connect("activate", self.__cb_item_add)
        self.builder.get_object("edit:profile_list:popup:remove").connect("activate", self.__cb_item_remove)
        widget.connect("button_press_event", self.__cb_button_pressed, self.builder.get_object("edit:profile_list:popup"))

        selection = self.get_TreeView().get_selection()
        selection.set_mode(gtk.SELECTION_SINGLE)
        self.section_list = self.builder.get_object("edit:section_list")
        self.profilesList = self.builder.get_object("edit:tw_profiles:sw")

        # actions
        self.add_sender(self.id, "update_profiles")
        self.add_receiver("gui:btn:menu:edit:profiles", "update", self.__update)
        selection.connect("changed", self.cb_item_changed, self.get_TreeView())

    def __update(self, new=False):

        if "profile" not in self.__dict__ or self.core.force_reload_profiles:
            self.data_model.fill(no_default=True)
            self.get_TreeView().get_model().foreach(self.set_selected, (self.core.selected_profile, self.get_TreeView()))
            self.core.force_reload_profiles = False
        if new: self.emit("update_profiles")

    def cb_item_changed(self, widget, treeView):

        selection = treeView.get_selection( )
        if selection != None: 
            (model, iter) = selection.get_selected( )
            if iter: self.core.selected_profile = model.get_value(iter, 0)
        self.emit("update")

    def __cb_button_pressed(self, treeview, event, menu):
        if event.button == 3:
            time = event.time
            menu.popup(None, None, None, event.button, event.time)

    def __cb_item_remove(self, widget):
        selection = self.get_TreeView().get_selection()
        (model,iter) = selection.get_selected()
        if iter:
            self.data_model.remove_item(model[iter][0])
            model.remove(iter)
        else: raise AttributeError, "Removing non-selected item or nothing selected."
        self.emit("update_profiles")

    def __cb_item_add(self, widget):
        EditAddProfileDialogWindow(self.core, self.data_model, self.__update)

class ItemList(abstract.List):

    def __init__(self, widget, core, builder=None, progress=None, filter=None):

        self.data_model = commands.DHItemsTree("gui:edit:DHItemsTree", core, progress, True, no_checks=True)
        self.edit_model = commands.DHEditItems()
        abstract.List.__init__(self, "gui:edit:item_list", core, widget)
        self.core = core
        self.loaded_new = True
        self.old_selected = None
        self.filter = filter
        self.map_filter = {}
        self.builder = builder

        # Popup Menu
        self.builder.get_object("edit:list:popup:add").connect("activate", self.__cb_item_add)
        self.builder.get_object("edit:list:popup:remove").connect("activate", self.__cb_item_remove)
        self.with_values = self.builder.get_object("edit:list:popup:show_values")
        self.with_values.connect("toggled", self.__update)
        widget.connect("button_press_event", self.__cb_button_pressed, self.builder.get_object("edit:list:popup"))

        self.section_list = self.builder.get_object("edit:section_list")
        self.itemsList = self.builder.get_object("edit:tw_items:sw")
        selection = self.get_TreeView().get_selection()
        selection.set_mode(gtk.SELECTION_SINGLE)

        # actions
        self.add_receiver("gui:btn:menu:edit:items", "update", self.__update)
        self.add_receiver("gui:btn:edit:filter", "search", self.__search)
        self.add_receiver("gui:btn:edit:filter", "filter_add", self.__filter_add)
        self.add_receiver("gui:btn:edit:filter", "filter_del", self.__filter_del)
        self.add_receiver("gui:edit:DHItemsTree", "filled", self.__filter_refresh)
        self.add_receiver("gui:btn:main:xccdf", "load", self.__loaded_new_xccdf)

        selection.connect("changed", self.__cb_item_changed, self.get_TreeView())
        self.add_sender(self.id, "item_changed")

        self.init_filters(self.filter, self.data_model.model, self.data_model.new_model())

    def __update(self, widget=None):

        if self.core.xccdf_file == None: self.data_model.model.clear()
        if self.loaded_new == True or widget != None:
            self.get_TreeView().set_model(self.data_model.model)
            self.data_model.fill(with_values=self.with_values.get_active())
            self.loaded_new = False
        # Select the last one selected if there is one         #self.core.selected_item_edit
        if self.old_selected != self.core.selected_item:
            self.get_TreeView().get_model().foreach(self.set_selected, (self.core.selected_item, self.get_TreeView()))
            self.core.force_reload_items = False
            self.old_selected = self.core.selected_item

    def __loaded_new_xccdf(self):
        self.loaded_new = True
        
    def __search(self):
        self.search(self.filter.get_search_text(),1)
        
    def __filter_add(self):
        self.map_filter = self.filter_add(self.filter.filters)
        self.get_TreeView().get_model().foreach(self.set_selected, (self.core.selected_item, self.get_TreeView()))

    def __filter_del(self):
        self.map_filter = self.filter_del(self.filter.filters)
        self.get_TreeView().get_model().foreach(self.set_selected, (self.core.selected_item, self.get_TreeView()))

    def __filter_refresh(self):
        self.map_filter = self.filter_del(self.filter.filters)
        self.get_TreeView().get_model().foreach(self.set_selected, (self.core.selected_item, self.get_TreeView()))

    def __cb_button_pressed(self, treeview, event, menu):
        if event.button == 3:
            time = event.time
            menu.popup(None, None, None, event.button, event.time)

    def __cb_item_remove(self, widget):
        selection = self.get_TreeView().get_selection()
        (model,iter) = selection.get_selected()
        if iter:
            self.data_model.remove_item(model[iter][1])
            model.remove(iter)
        else: raise AttributeError, "Removing non-selected item or nothing selected."

    def __cb_item_add(self, widget):
        selection = self.get_TreeView().get_selection()
        (model,iter) = selection.get_selected()
        if iter:
            AddItem(self.core, self.data_model, self, self.ref_model)
        else: AddItem(self.core, None, self, self.ref_model)

    @threadSave
    def __cb_item_changed(self, widget, treeView):
        """Make all changes in application in separate threads: workaround for annoying
        blinking when redrawing treeView
        """
        gtk.gdk.threads_enter()
        details = self.data_model.get_item_details(self.core.selected_item)
        if details != None:
            self.item = details["item"]
        else: self.item = None
        selection = treeView.get_selection( )
        if selection != None: 
            (model, iter) = selection.get_selected( )
            if iter: 
                self.core.selected_item = model.get_value(iter, commands.DHItemsTree.COLUMN_ID)
                #self.core.selected_item_edit = model.get_value(iter, 0)
            else:
                self.core.selected_item = None
                #self.core.selected_item_edit = None
        self.emit("update")
        treeView.columns_autosize()
        gtk.gdk.threads_leave()


class MenuButtonEditXCCDF(abstract.MenuButton):

    def __init__(self, builder, widget, core):
        abstract.MenuButton.__init__(self, "gui:btn:menu:edit:XCCDF", widget, core)
        self.builder = builder
        self.core = core
        self.data_model = commands.DHXccdf(core)
        
        #draw body
        self.body = self.builder.get_object("edit_xccdf:box")
        self.add_receiver("gui:btn:main:xccdf", "load", self.__update)
        self.add_receiver("gui:btn:main:xccdf", "update", self.__update)
        self.add_sender(self.id, "update")

        # Get widgets from glade
        self.entry_id = self.builder.get_object("edit:xccdf:id")
        self.entry_id.connect( "changed", self.__change, "id")
        self.entry_version = self.builder.get_object("edit:xccdf:version")
        self.entry_version.connect( "changed", self.__change, "version")
        self.entry_resolved = self.builder.get_object("edit:xccdf:resolved")
        self.entry_resolved.connect( "changed", self.__change, "resolved")
        self.entry_lang = self.builder.get_object("edit:xccdf:lang")
        self.entry_lang.connect( "changed", self.__change, "lang")

        # -- TITLE --
        self.titles = EditTitle(self.core, "gui:edit:xccdf:title", builder.get_object("edit:xccdf:titles"), self.data_model)
        builder.get_object("edit:xccdf:btn_titles_add").connect("clicked", self.titles.dialog, self.data_model.CMD_OPER_ADD)
        builder.get_object("edit:xccdf:btn_titles_edit").connect("clicked", self.titles.dialog, self.data_model.CMD_OPER_EDIT)
        builder.get_object("edit:xccdf:btn_titles_del").connect("clicked", self.titles.dialog, self.data_model.CMD_OPER_DEL)

        # -- DESCRIPTION --
        self.descriptions = EditDescription(self.core, "gui:edit:xccdf:description", builder.get_object("edit:xccdf:descriptions"), self.data_model)
        self.builder.get_object("edit:xccdf:btn_descriptions_add").connect("clicked", self.descriptions.dialog, self.data_model.CMD_OPER_ADD)
        self.builder.get_object("edit:xccdf:btn_descriptions_edit").connect("clicked", self.descriptions.dialog, self.data_model.CMD_OPER_EDIT)
        self.builder.get_object("edit:xccdf:btn_descriptions_del").connect("clicked", self.descriptions.dialog, self.data_model.CMD_OPER_DEL)
        self.builder.get_object("edit:xccdf:btn_descriptions_preview").connect("clicked", self.descriptions.preview)

        # -- WARNING --
        self.warnings = EditWarning(self.core, "gui:edit:xccdf:warning", builder.get_object("edit:xccdf:warnings"), self.data_model)
        self.builder.get_object("edit:xccdf:btn_warnings_add").connect("clicked", self.warnings.dialog, self.data_model.CMD_OPER_ADD)
        self.builder.get_object("edit:xccdf:btn_warnings_edit").connect("clicked", self.warnings.dialog, self.data_model.CMD_OPER_EDIT)
        self.builder.get_object("edit:xccdf:btn_warnings_del").connect("clicked", self.warnings.dialog, self.data_model.CMD_OPER_DEL)

        # -- NOTICE --
        self.notices = EditNotice(self.core, "gui:edit:xccdf:notice", builder.get_object("edit:xccdf:notices"), self.data_model)
        self.builder.get_object("edit:xccdf:btn_notices_add").connect("clicked", self.notices.dialog, self.data_model.CMD_OPER_ADD)
        self.builder.get_object("edit:xccdf:btn_notices_edit").connect("clicked", self.notices.dialog, self.data_model.CMD_OPER_EDIT)
        self.builder.get_object("edit:xccdf:btn_notices_del").connect("clicked", self.notices.dialog, self.data_model.CMD_OPER_DEL)

        # -- REFERENCE --
        self.tv_references = abstract.ListEditor("gui:edit:xccdf:references", self.core, widget=self.builder.get_object("edit:xccdf:references"), model=gtk.ListStore(str, str))
        self.tv_references.widget.append_column(gtk.TreeViewColumn("Reference", gtk.CellRendererText(), text=0))
        self.builder.get_object("edit:xccdf:btn_references_add").set_sensitive(False)
        self.builder.get_object("edit:xccdf:btn_references_edit").set_sensitive(False)
        self.builder.get_object("edit:xccdf:btn_references_del").set_sensitive(False)

        # -- STATUS --
        self.statuses = EditStatus(self.core, "gui:edit:xccdf:status", builder.get_object("edit:xccdf:statuses"), self.data_model)
        self.builder.get_object("edit:xccdf:btn_statuses_add").connect("clicked", self.statuses.dialog, self.data_model.CMD_OPER_ADD)
        self.builder.get_object("edit:xccdf:btn_statuses_edit").connect("clicked", self.statuses.dialog, self.data_model.CMD_OPER_EDIT)
        self.builder.get_object("edit:xccdf:btn_statuses_del").connect("clicked", self.statuses.dialog, self.data_model.CMD_OPER_DEL)
        # -------------

    def __change(self, widget, object=None):

        if object == "id":
            self.data_model.update(id=widget.get_text())
        elif object == "version":
            self.data_model.update(version=widget.get_text())
        elif object == "resolved":
            self.data_model.update(resolved=(widget.get_active() == 1))
        elif object == "status":
            self.data_model.update(status=abstract.ENUM_STATUS_CURRENT[widget.get_active()][0])
        elif object == "lang":
            self.data_model.update(lang=widget.get_text())
        else: 
            logger.error("Change \"%s\" not supported object in \"%s\"" % (object, widget))
            return
        self.emit("update")

    def __clear_widgets(self):
        """Clear widgets
        """
        self.titles.clear()
        self.descriptions.clear()
        self.warnings.clear()
        self.notices.clear()
        self.statuses.clear()
        self.tv_references.clear()
        self.entry_id.set_text("")
        self.entry_version.set_text("")
        self.entry_resolved.set_active(-1)
        self.entry_lang.set_text("")


    def __update(self):

        # TODO: this blocks of handlers could be substitute ?        
        self.entry_id.handler_block_by_func(self.__change)
        self.entry_version.handler_block_by_func(self.__change)
        self.entry_resolved.handler_block_by_func(self.__change)
        self.entry_lang.handler_block_by_func(self.__change)

        self.__clear_widgets()
        details = self.data_model.get_details()

        """Set sensitivity of widgets depended on availability of XCCDF details
        This is mainly supposed to control no-XCCDF or loaded XCCDF behavior
        """
        self.builder.get_object("edit:xccdf:notebook").set_sensitive(details != None)
        self.builder.get_object("edit:xccdf:entries").set_sensitive(details != None)

        """Update 
        """
        if details:
            self.entry_id.set_text(details["id"] or "")
            self.entry_version.set_text(details["version"] or "")
            self.entry_resolved.set_active(details["resolved"])
            self.entry_lang.set_text(details["lang"] or "")
            self.titles.fill()
            self.descriptions.fill()
            self.warnings.fill()
            self.notices.fill()
            for ref in details["references"]:
                self.tv_references.append([ref])
            self.statuses.fill()

        self.entry_id.handler_unblock_by_func(self.__change)
        self.entry_version.handler_unblock_by_func(self.__change)
        self.entry_resolved.handler_unblock_by_func(self.__change)
        self.entry_lang.handler_unblock_by_func(self.__change)

        
class MenuButtonEditProfiles(abstract.MenuButton, abstract.ControlEditWindow):

    def __init__(self, builder, widget, core):
        abstract.MenuButton.__init__(self, "gui:btn:menu:edit:profiles", widget, core)
        self.builder = builder
        self.core = core
        self.profile_model = commands.DHProfiles(self.core)
        self.item = None
        self.func = abstract.Func()
        
        #draw body
        self.body = self.builder.get_object("edit_profile:box")
        self.tw_profiles = self.builder.get_object("edit:tw_profiles")
        self.list_profile = ProfileList(self.tw_profiles, self.core, builder, None, None)

        # set signals
        self.add_receiver("gui:edit:profile_list", "update", self.__update)
        self.add_receiver("gui:edit:profile_list", "changed", self.__update)
        self.add_receiver("gui:btn:main:xccdf", "load", self.__update)
        self.add_receiver("gui:btn:main:xccdf", "update", self.__update)
        self.add_sender(self.id, "update")
        
       # PROFILES
        self.info_box_lbl = self.builder.get_object("edit:profile:info_box:lbl")
        self.profile_id = self.builder.get_object("edit:profile:entry_id")
        self.profile_cb_lang = self.builder.get_object("edit:profile:cbentry_lang")
        for lang in self.core.langs:
            self.profile_cb_lang.get_model().append([lang])
        self.profile_title = self.builder.get_object("edit:profile:entry_title")
        self.profile_version = self.builder.get_object("edit:profile:entry_version")
        self.profile_description = self.builder.get_object("edit:profile:entry_description")
        self.profile_abstract = self.builder.get_object("edit:profile:cbox_abstract")
        self.profile_extends = self.builder.get_object("edit:profile:cb_extends")
        self.tw_langs = self.builder.get_object("edit:profile:tw_langs")

        self.profile_btn_revert = self.builder.get_object("edit:profile:btn_revert")
        self.profile_btn_revert.connect("clicked", self.__cb_profile_revert)
        self.profile_btn_save = self.builder.get_object("edit:profile:btn_save")
        self.profile_btn_save.connect("clicked", self.__cb_profile_save)
        self.profile_btn_add = self.builder.get_object("edit:profile:btn_add")
        self.profile_btn_add.connect("clicked", self.__cb_profile_add_lang)

        selection = self.tw_langs.get_selection()
        selection.connect("changed", self.__cb_profile_lang_changed)
        self.langs_model = gtk.ListStore(str, str, str)
        self.tw_langs.set_model(self.langs_model)
        self.tw_langs.append_column(gtk.TreeViewColumn("Lang", gtk.CellRendererText(), text=0))
        self.tw_langs.append_column(gtk.TreeViewColumn("Title", gtk.CellRendererText(), text=1))
        self.tw_langs.append_column(gtk.TreeViewColumn("Description", gtk.CellRendererText(), text=2))
        
    def __cb_profile_revert(self, widget):
        self.__update()

    def __cb_profile_save(self, widget):
        if self.profile_id.get_text() == "":
            logger.error("No ID of profile specified")
            md = gtk.MessageDialog(self.window, 
                    gtk.DIALOG_MODAL, gtk.MESSAGE_ERROR,
                    gtk.BUTTONS_OK, "ID of profile has to be specified !")
            md.run()
            md.destroy()
            return
        values = {}
        values["id"] = self.profile_id.get_text()
        values["abstract"] = self.profile_abstract.get_active()
        values["version"] = self.profile_version.get_text()
        if self.profile_extends.get_active() >= 0: values["extends"] = self.profile_extends.get_model()[self.profile_extends.get_active()][0]
        else: values["extends"] = None
        values["details"] = []
        for row in self.tw_langs.get_model():
            item = {"lang": row[0],
                    "title": row[1],
                    "description": row[2]}
            values["details"].append(item)

        self.profile_model.edit(values)
        self.core.force_reload_profiles = True
        self.profile_model.save()
        self.emit("update")
        
    def __update(self):

        self.profile_title.set_text("")
        self.profile_description.get_buffer().set_text("")
        details = self.profile_model.get_profile_details(self.core.selected_profile)
        self.tw_langs.get_model().clear()
        self.profile_btn_add.set_sensitive(details != None)
        self.profile_btn_save.set_sensitive(details != None)
        self.profile_btn_revert.set_sensitive(details != None)
        self.builder.get_object("edit:profile").set_sensitive(details != None)
        self.builder.get_object("edit:tw_profiles:box").set_sensitive(details != None)

        if not details:
            self.profile_id.set_text("")
            self.profile_abstract.set_active(False)
            #self.profile_extend.set_text("")
            self.profile_version.set_text("")
            self.profile_title.set_text("")
            return

        self.profile_description.set_sensitive(details["id"] != None)
        self.profile_title.set_sensitive(details["id"] != None)
        self.profile_abstract.set_sensitive(details["id"] != None)
        self.profile_id.set_sensitive(details["id"] != None)
        self.profile_version.set_sensitive(details["id"] != None)
        self.tw_langs.set_sensitive(details["id"] != None)
        self.profile_cb_lang.set_sensitive(details["id"] != None)
        self.profile_btn_add.set_sensitive(details["id"] != None)
        self.profile_btn_save.set_sensitive(details["id"] != None)
        self.profile_btn_revert.set_sensitive(details["id"] != None)

        self.profile_id.set_text(details["id"] or "")
        self.profile_abstract.set_active(details["abstract"])
        #self.profile_extend.set_text(str(details["extends"] or ""))
        self.profile_version.set_text(details["version"] or "")

        title = None
        description = None
        for lang in details["titles"]:
            if lang in details["titles"]: title = details["titles"][lang]
            if lang in details["descriptions"]: description = details["descriptions"][lang]
            self.tw_langs.get_model().append([lang, title, description])
            
    def __cb_profile_lang_changed(self, widget):
        selection = self.tw_langs.get_selection( )
        if selection != None: 
            (model, iter) = selection.get_selected( )
            if iter: 
                self.__set_lang(self.profile_cb_lang, model.get_value(iter, 0))
                self.profile_title.set_text(model.get_value(iter, 1))
                if model.get_value(iter, 2): 
                    self.profile_description.get_buffer().set_text(model.get_value(iter, 2))

    def __cb_profile_add_lang(self, widget):
        result = None
        for row in self.tw_langs.get_model():
            if row[0] == self.profile_cb_lang.get_active_text():
                md = gtk.MessageDialog(self.core.main_window, 
                        gtk.DIALOG_MODAL, gtk.MESSAGE_QUESTION,
                        gtk.BUTTONS_YES_NO, "Language \"%s\" already specified.\n\nRewrite stored data ?" % (row[0],))
                md.set_title("Language found")
                result = md.run()
                md.destroy()
                if result == gtk.RESPONSE_NO: 
                    return
                else: self.langs_model.remove(row.iter)

        buffer = self.profile_description.get_buffer()
        self.tw_langs.get_model().append([self.profile_cb_lang.get_active_text(), 
            self.profile_title.get_text(),
            buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)])

        # Add lang to combo box model
        found = False
        for item in self.profile_cb_lang.get_model():
            if item[0] == self.profile_cb_lang.get_active_text(): 
                found = True
        if not found: 
            self.profile_cb_lang.get_model().append([self.profile_cb_lang.get_active_text()])
            self.profile_cb_lang.set_active_iter(self.profile_cb_lang.get_model()[-1].iter)
            self.core.langs.append(self.profile_cb_lang.get_active_text())

        # Clear
        self.profile_cb_lang.set_active(-1)
        self.profile_title.set_text("")
        self.profile_description.get_buffer().set_text("")
        
    def __set_lang(self, widget, lang):

        _set = False
        model =  widget.get_model()
        iter = model.get_iter_first()
        while iter:
            if lang == model.get_value(iter, 0):
                widget.set_active_iter(iter) 
                _set = True
                break
            iter = model.iter_next(iter)
        if not _set: 
            iter = model.append([lang])
            widget.set_active_iter(iter)
            
class MenuButtonEditItems(abstract.MenuButton, abstract.ControlEditWindow):
    """
    GUI for refines.
    """
    def __init__(self, builder, widget, core):
        abstract.MenuButton.__init__(self, "gui:btn:menu:edit:items", widget, core)
        self.builder = builder
        self.core = core
        self.data_model = commands.DHEditItems(self.core)
        self.item = None
        self.func = abstract.Func()
        self.current_page = 0

        #draw body
        self.body = self.builder.get_object("edit_item:box")
        self.progress = self.builder.get_object("edit:progress")
        self.progress.hide()
        self.filter = filter.ItemFilter(self.core, self.builder,"edit:box_filter", "gui:btn:edit:filter")
        self.filter.set_active(False)
        self.tw_items = self.builder.get_object("edit:tw_items")
        titles = self.data_model.get_benchmark_titles()
        self.list_item = ItemList(self.tw_items, self.core, builder, self.progress, self.filter)
        self.ref_model = self.list_item.get_TreeView().get_model() # original model (not filtered)
        
        # set signals
        self.add_sender(self.id, "update")
        
        # remove just for now (missing implementations and so..)
        self.items = self.builder.get_object("edit:xccdf:items")
        self.items.remove_page(4)

        # Get widgets from GLADE
        self.item_id = self.builder.get_object("edit:general:entry_id")
        self.version = self.builder.get_object("edit:general:entry_version")
        self.version.connect("focus-out-event", self.__change)
        self.version.connect("key-press-event", self.__change)
        self.version_time = self.builder.get_object("edit:general:entry_version_time")
        self.version_time.connect("focus-out-event", self.__change)
        self.version_time.connect("key-press-event", self.__change)
        self.selected = self.builder.get_object("edit:general:chbox_selected")
        self.selected.connect("toggled", self.__change)
        self.hidden = self.builder.get_object("edit:general:chbox_hidden")
        self.hidden.connect("toggled", self.__change)
        self.prohibit = self.builder.get_object("edit:general:chbox_prohibit")
        self.prohibit.connect("toggled", self.__change)
        self.abstract = self.builder.get_object("edit:general:chbox_abstract")
        self.abstract.connect("toggled", self.__change)
        self.cluster_id = self.builder.get_object("edit:general:entry_cluster_id")
        self.cluster_id.connect("focus-out-event", self.__change)
        self.cluster_id.connect("key-press-event", self.__change)
        self.weight = self.builder.get_object("edit:general:entry_weight")
        self.weight.connect("focus-out-event", self.__change)
        self.weight.connect("key-press-event", self.__change)
        self.operations = self.builder.get_object("edit:xccdf:items:operations")
        self.extends = self.builder.get_object("edit:dependencies:lbl_extends")
        self.item_values_main = self.builder.get_object("edit:values:sw_main")
        
        # -- TITLES --
        self.titles = EditTitle(self.core, "gui:edit:xccdf:items:titles", builder.get_object("edit:general:lv_title"), self.data_model)
        builder.get_object("edit:general:btn_title_add").connect("clicked", self.titles.dialog, self.data_model.CMD_OPER_ADD)
        builder.get_object("edit:general:btn_title_edit").connect("clicked", self.titles.dialog, self.data_model.CMD_OPER_EDIT)
        builder.get_object("edit:general:btn_title_del").connect("clicked", self.titles.dialog, self.data_model.CMD_OPER_DEL)

        # -- DESCRIPTIONS --
        self.descriptions = EditDescription(self.core, "gui:edit:xccdf:items:descriptions", builder.get_object("edit:general:lv_description"), self.data_model)
        builder.get_object("edit:general:btn_description_add").connect("clicked", self.descriptions.dialog, self.data_model.CMD_OPER_ADD)
        builder.get_object("edit:general:btn_description_edit").connect("clicked", self.descriptions.dialog, self.data_model.CMD_OPER_EDIT)
        builder.get_object("edit:general:btn_description_del").connect("clicked", self.descriptions.dialog, self.data_model.CMD_OPER_DEL)
        builder.get_object("edit:general:btn_description_preview").connect("clicked", self.descriptions.preview)

        # -- WARNINGS --
        self.warnings = EditWarning(self.core, "gui:edit:items:general:warning", builder.get_object("edit:general:lv_warning"), self.data_model)
        builder.get_object("edit:general:btn_warning_add").connect("clicked", self.warnings.dialog, self.data_model.CMD_OPER_ADD)
        builder.get_object("edit:general:btn_warning_edit").connect("clicked", self.warnings.dialog, self.data_model.CMD_OPER_EDIT)
        builder.get_object("edit:general:btn_warning_del").connect("clicked", self.warnings.dialog, self.data_model.CMD_OPER_DEL)

        # -- STATUSES --
        self.statuses = EditStatus(self.core, "gui:edit:items:general:status", builder.get_object("edit:general:lv_status"), self.data_model)
        builder.get_object("edit:general:btn_status_add").connect("clicked", self.statuses.dialog, self.data_model.CMD_OPER_ADD)
        builder.get_object("edit:general:btn_status_edit").connect("clicked", self.statuses.dialog, self.data_model.CMD_OPER_EDIT)
        builder.get_object("edit:general:btn_status_del").connect("clicked", self.statuses.dialog, self.data_model.CMD_OPER_DEL)

        # -- QUESTIONS --
        self.questions = EditQuestion(self.core, "gui:edit:items:general:questions", builder.get_object("edit:items:questions"), self.data_model)
        builder.get_object("edit:items:questions:btn_add").connect("clicked", self.questions.dialog, self.data_model.CMD_OPER_ADD)
        builder.get_object("edit:items:questions:btn_edit").connect("clicked", self.questions.dialog, self.data_model.CMD_OPER_EDIT)
        builder.get_object("edit:items:questions:btn_del").connect("clicked", self.questions.dialog, self.data_model.CMD_OPER_DEL)

        # -- RATIONALES --
        self.rationales = EditRationale(self.core, "gui:edit:items:general:rationales", builder.get_object("edit:items:rationales"), self.data_model)
        builder.get_object("edit:items:rationales:btn_add").connect("clicked", self.rationales.dialog, self.data_model.CMD_OPER_ADD)
        builder.get_object("edit:items:rationales:btn_edit").connect("clicked", self.rationales.dialog, self.data_model.CMD_OPER_EDIT)
        builder.get_object("edit:items:rationales:btn_del").connect("clicked", self.rationales.dialog, self.data_model.CMD_OPER_DEL)

        # -- VALUES --
        self.item_values = EditItemValues(self.core, "gui:edit:items:values", builder.get_object("edit:xccdf:items:values"), self.data_model)
        builder.get_object("edit:xccdf:items:values:btn_add").connect("clicked", self.item_values.dialog, self.data_model.CMD_OPER_ADD)
        builder.get_object("edit:xccdf:items:values:btn_del").connect("clicked", self.item_values.dialog, self.data_model.CMD_OPER_DEL)

        # -------------

        """Get widgets from Glade: Part main.glade in edit
        """
        self.conflicts = EditConflicts(self.core, self.builder,self.list_item.get_TreeView().get_model())
        self.requires = EditRequires(self.core, self.builder,self.list_item.get_TreeView().get_model())
        self.ident = EditIdent(self.core, self.builder)
        self.platform = EditPlatform(self.core, self.builder)
        self.values = EditValues(self.core, "gui:edit:xccdf:values", self.builder)
        self.fixtext = EditFixtext(self.core, self.builder)
        self.fix = EditFix(self.core, self.builder)
        
        self.severity = self.builder.get_object("edit:operations:combo_severity")
        self.set_model_to_comboBox(self.severity,self.combo_model_level, self.COMBO_COLUMN_VIEW)
        self.severity.connect( "changed", self.__change)
        self.impact_metric = self.builder.get_object("edit:operations:entry_impact_metric")
        self.impact_metric.connect("focus-out-event", self.cb_control_impact_metrix)
        self.check = self.builder.get_object("edit:operations:lv_check")
        
        #others
        #self.multiple = self.builder.get_object("edit:other:chbox_multiple")
        #self.multiple.connect("toggled",self.data_model.cb_chbox_multipl)

        #self.role = self.builder.get_object("edit:other:combo_role")
        #self.set_model_to_comboBox(self.role, self.combo_model_role, self.COMBO_COLUMN_VIEW)
        #self.role.connect( "changed", self.data_model.cb_cBox_role)

        self.add_receiver("gui:edit:item_list", "update", self.__update)
        self.add_receiver("gui:edit:item_list", "changed", self.__update)
        self.add_receiver("gui:edit:xccdf:values", "update", self.__update_item)
        self.add_receiver("gui:edit:xccdf:values:titles", "update", self.__update_item)

    def __change(self, widget, event=None):

        if event and event.type == gtk.gdk.KEY_PRESS and event.keyval != gtk.keysyms.Return:
            return

        if widget == self.version:
            self.data_model.update(version=widget.get_text())
        elif widget == self.version_time:
            timestamp = self.controlDate(widget.get_text())
            if timestamp:
                self.data_model.update(version_time=timestamp)
        elif widget == self.selected:
            self.data_model.update(selected=widget.get_active())
        elif widget == self.hidden:
            self.data_model.update(hidden=widget.get_active())
        elif widget == self.prohibit:
            self.data_model.update(prohibit=widget.get_active())
        elif widget == self.abstract:
            self.data_model.update(abstract=widget.get_active())
        elif widget == self.cluster_id:
            self.data_model.update(cluster_id=widget.get_text())
        elif widget == self.weight:
            weight = self.controlFloat(widget.get_text(), "Weight")
            if weight:
                self.data_model.update(weight=weight)
        else: 
            logger.error("Change \"%s\" not supported object in \"%s\"" % (object, widget))
            return
        #self.emit("update")

    def cb_chbox_selected(self, widget):

        selection = self.tw_items.get_selection()
        (model, iter) = selection.get_selected()
        if iter:
            if model != self.ref_model:
                map, struct = self.list_item.map_filter
                path = map[model.get_path(iter)]
                iter = self.ref_model.get_iter(path)
                model= self.ref_model   
            model.set_value(iter, 5, widget.get_active())
            self.data_model.DHEditChboxSelected(widget, self.item)

    def __section_list_load(self):
        self.section_list.get_model().clear()
        titles = self.data_model.get_benchmark_titles()
        if len(titles.keys()) != 0:
            if self.core.selected_lang in titles: 
                title = self.data_model.get_benchmark_titles()[self.core.selected_lang]
            else: 
                self.data_model.get_benchmark_titles()[0]
            self.section_list.get_model().append(["XCCDF", "XCCDF: "+title])
            self.section_list.get_model().append(["PROFILES", "XCCDF: "+title+" (Profiles)"])
            self.section_list.set_active(0)

    def cb_control_impact_metrix(self, widget, event):
        text = widget.get_text()
        if text != "" and self.controlImpactMetric(text):
            self.data_model.DHEditImpactMetrix(self.item, text)

    def show(self, sensitive):
        self.items.set_sensitive(sensitive)
        self.items.set_visible(sensitive)

    def __set_profile_description(self, description):
        """
        Set description to the textView.
        @param text Text with description
        """
        self.profile_description.get_buffer().set_text("")
        if description == "": description = "No description"
        description = "<body>"+description+"</body>"
        self.profile_description.display_html(description)

    def __update_item(self):
        selection = self.tw_items.get_selection()
        (model, iter) = selection.get_selected()
        if iter:
            item = self.data_model.get_item_details(model[iter][1])
            if item == None:
                logger.error("Can't find item with ID: \"%s\"" % (model[iter][1],))
                return
            model[iter][1] = item["id"] # TODO

            # Get the title of item
            title = title = item["id"]+" (ID)"
            if len(item["titles"]) > 0:
                if self.core.selected_lang in item["titles"].keys(): title = item["titles"][self.core.selected_lang]
                else: title = item["titles"][item["titles"].keys()[0]]+" ["+item["titles"].keys()[0]+"]"

            model[iter][2] = title
            model[iter][4] = ""+title

    def __block_signals(self):
        self.hidden.handler_block_by_func(self.__change)
        self.selected.handler_block_by_func(self.__change)
        self.prohibit.handler_block_by_func(self.__change)
        self.abstract.handler_block_by_func(self.__change)
        self.severity.handler_block_by_func(self.__change)
        #self.multiple.handler_block_by_func(self.__change)
        #self.role.handler_block_by_func(self.__change)

    def __unblock_signals(self):
        self.hidden.handler_unblock_by_func(self.__change)
        self.selected.handler_unblock_by_func(self.__change)
        self.prohibit.handler_unblock_by_func(self.__change)
        self.abstract.handler_unblock_by_func(self.__change)
        self.severity.handler_unblock_by_func(self.__change)
        #self.chbox_multiple.handler_unblock_by_func(self.__change)
        #self.cBox_role.handler_unblock_by_func(self.__change)

    def __clear(self):
        self.__block_signals()
        self.item_id.set_text("")
        self.hidden.set_active(False)
        self.selected.set_active(False)
        self.prohibit.set_active(False)
        self.abstract.set_active(False)
        self.version.set_text("")
        self.version_time.set_text("")
        self.cluster_id.set_text("")
        #self.extends.set_text("None")

        self.titles.clear()
        self.descriptions.clear()
        self.warnings.clear()
        self.statuses.clear()
        self.questions.clear()
        self.rationales.clear()
        self.item_values.clear()
        self.conflicts.fill(None)
        self.requires.fill(None)
        self.platform.fill(None)
        self.fix.fill(None)
        self.fixtext.fill(None)
        self.__unblock_signals()

    def __update(self):
 
        if self.core.selected_item != None:
            details = self.data_model.get_item_details(self.core.selected_item)
        else:
            details = None
            #self.item = None
        
        self.__clear()
        if details == None:
            self.set_sensitive(False)
            return

        # Check if the item is value and change widgets
        if details["type"] == openscap.OSCAP.XCCDF_VALUE:
            self.show(False)
            self.values.show(True)
            self.values.update()
            return
        else: 
            self.show(True)
            self.values.show(False)

        # Item is not value, continue
        self.__block_signals()
        self.item_id.set_text(details["id"] or "")
        self.weight.set_text(str(details["weight"] or ""))
        self.version.set_text(details["version"] or "")
        self.version_time.set_text(str(datetime.date.fromtimestamp(details["version_time"]) or ""))
        self.cluster_id.set_text(details["cluster_id"] or "")
        self.extends.set_text(details["extends"] or "")
        self.titles.fill()
        self.descriptions.fill()
        self.warnings.fill()
        self.statuses.fill()
        self.questions.fill()
        self.rationales.fill()
        self.conflicts.fill(details)
        self.requires.fill(details["item"])
        self.platform.fill(details["item"])

        self.abstract.set_active(details["abstract"])
        self.selected.set_active(details["selected"])
        self.hidden.set_active(details["hidden"])
        self.prohibit.set_active(details["prohibit_changes"])

        self.set_sensitive(True)

        if details["type"] == openscap.OSCAP.XCCDF_RULE: # Item is Rule
            self.ident.set_sensitive(True)
            self.item_values_main.set_sensitive(True)
            self.operations.set_sensitive(True)

            self.severity.set_active(abstract.ENUM_LEVEL.pos(details["severity"]) or -1)
            self.impact_metric.set_text(details["imapct_metric"] or "")
            self.fixtext.fill(details["item"])
            self.fix.fill(details["item"])
            self.ident.fill(details["item"])
            self.item_values.fill()
            #self.role.set_active(abstract.ENUM_ROLE.pos(details["role"]) or -1)
            #self.multiple.set_active(details["multiple"] or -1)
            #self.values.fill(None)
            
        else: # Item is GROUP
            # clean data only for rule and set insensitive
            self.ident.set_sensitive(False)
            self.item_values_main.set_sensitive(False)
            self.operations.set_sensitive(False)

            self.severity.set_active(-1)
            self.impact_metric.set_text("")
            self.fixtext.fill(None)
            self.fix.fill(None)
            self.ident.fill(None)
            #self.role.set_active(-1)

        self.__unblock_signals()
                
            
class EditConflicts(commands.DHEditItems, abstract.ControlEditWindow):
    
    COLUMN_ID = 0
    
    def __init__(self, core, builder, model_item):
        self.model_item = model_item
        lv = builder.get_object("edit:dependencies:lv_conflict")
        model = gtk.ListStore(str)
        lv.set_model(model)
        
        abstract.ControlEditWindow.__init__(self, core, lv, None)
        btn_add = builder.get_object("edit:dependencies:btn_conflict_add")
        btn_del = builder.get_object("edit:dependencies:btn_conflict_del")
        
        # set callBack to btn
        btn_add.connect("clicked", self.__cb_add)
        btn_del.connect("clicked", self.__cb_del_row)

        self.addColumn("ID Item",self.COLUMN_ID)

    def fill(self, details):
        if details == None:
            return
        self.item = details["item"]
        self.model.clear()
        for data in details["conflicts"]:
            self.model.append([data])
    
    def __cb_add(self, widget):
        EditSelectIdDialogWindow(self.item, self.core, self.model, self.model_item, self.DHEditConflicts)
    
    
    def __cb_del_row(self, widget):
        pass

class EditRequires(commands.DHEditItems,abstract.ControlEditWindow):
    
    COLUMN_ID = 0
    
    def __init__(self, core, builder, model_item):
        self.model_item = model_item
        lv = builder.get_object("edit:dependencies:lv_requires")
        model = gtk.ListStore(str)
        lv.set_model(model)

        abstract.ControlEditWindow.__init__(self, core, lv, None)
        btn_add = builder.get_object("edit:dependencies:btn_requires_add")
        btn_del = builder.get_object("edit:dependencies:btn_requires_del")
        
        # set callBack to btn
        btn_add.connect("clicked", self.__cb_add)
        btn_del.connect("clicked", self.__cb_del_row)

        self.addColumn("ID Item", self.COLUMN_ID)

    def fill(self, item):
        self.item = item
        self.model.clear()
        if item:
            for data in item.requires:
                self.model.append([data])
    
    def __cb_add(self, widget):
        EditSelectIdDialogWindow(self.item, self.core, self.model, self.model_item, self.DHEditRequires)
    
    def __cb_del_row(self, widget):
        pass
    
class EditItemValues(abstract.ListEditor):

    COLUMN_ID       = 0
    COLUMN_VALUE    = 1
    COLUMN_OBJ      = 2

    def __init__(self, core, id, widget, data_model):

        self.data_model = data_model
        abstract.ListEditor.__init__(self, id, core, widget=widget, model=gtk.ListStore(str, str, gobject.TYPE_PYOBJECT))
        #self.add_sender(id, "update")

        self.widget.append_column(gtk.TreeViewColumn("ID", gtk.CellRendererText(), text=self.COLUMN_ID))
        self.widget.append_column(gtk.TreeViewColumn("Value", gtk.CellRendererText(), text=self.COLUMN_VALUE))

    def __do(self, widget=None):
        """
        """
        self.core.notify_destroy("notify:dialog_notify")
        item = None
        (model, iter) = self.values.get_selection().get_selected()
        if iter:
            item = model[iter][self.COLUMN_ID]
        else:
            self.core.notify("Value has to be choosen.", 2, info_box=self.info_box, msg_id="notify:dialog_notify")
            return

        self.data_model.item_edit_value(self.operation, item)
        self.fill()
        self.__dialog_destroy()
        self.emit("update")

    def __dialog_destroy(self, widget=None):
        """
        """
        if self.dialog: 
            self.dialog.destroy()

    def filter_treeview(self, model, iter, data):
        text = self.search.get_text()
        if len(text) == 0: 
            return True
        pattern = re.compile(text, re.I)
        for col in data:
            found = re.search(pattern, model[iter][col])
            if found != None: return True
        return False

    def search_treeview(self, widget, treeview):
        treeview.get_model().refilter()
        return

    def dialog(self, widget, operation):
        """
        """
        self.operation = operation
        builder = gtk.Builder()
        builder.add_from_file("/usr/share/scap-workbench/edit_item.glade")
        self.dialog = builder.get_object("dialog:find_value")
        self.info_box = builder.get_object("dialog:find_value:info_box")
        self.values = builder.get_object("dialog:find_value:values")
        self.search = builder.get_object("dialog:find_value:search")
        self.search.connect("changed", self.search_treeview, self.values)
        builder.get_object("dialog:find_value:btn_cancel").connect("clicked", self.__dialog_destroy)
        builder.get_object("dialog:find_value:btn_ok").connect("clicked", self.__do)

        self.core.notify_destroy("notify:not_selected")
        (model, self.iter) = self.get_selection().get_selected()
        if operation == self.data_model.CMD_OPER_ADD:
            self.values.append_column(gtk.TreeViewColumn("ID of Value", gtk.CellRendererText(), text=self.COLUMN_ID))
            self.values.append_column(gtk.TreeViewColumn("Title", gtk.CellRendererText(), text=self.COLUMN_VALUE))
            values = self.data_model.get_all_values()
            self.values.set_model(gtk.ListStore(str, str, gobject.TYPE_PYOBJECT))
            modelfilter = self.values.get_model().filter_new()
            modelfilter.set_visible_func(self.filter_treeview, data=[0,1])
            self.values.set_model(modelfilter)
            for value in values: 
                item = self.data_model.parse_value(value)
                if len(item["titles"]) > 0:
                    if self.core.selected_lang in item["titles"].keys(): title = item["titles"][self.core.selected_lang]
                    else: title = item["titles"][item["titles"].keys()[0]]+" ["+item["titles"].keys()[0]+"]"
                self.values.get_model().get_model().append([value.id, title, value])

            self.dialog.set_transient_for(self.core.main_window)
            self.dialog.show_all()
        elif operation == self.data_model.CMD_OPER_DEL:
            if not self.iter:
                self.notifications.append(self.core.notify("Please select at least one item to delete", 2, msg_id="notify:not_selected"))
                return
            else: 
                iter = self.dialogDel(self.core.main_window, self.get_selection())
                if iter != None:
                    self.__do()
                return
        else: 
            logger.error("Unknown operation for title dialog: \"%s\"" % (operation,))
            return

    def fill(self):
        """
        """
        self.clear()
        for item in self.data_model.get_item_values(self.core.selected_item):
            if len(item["titles"]) > 0:
                if self.core.selected_lang in item["titles"].keys(): title = item["titles"][self.core.selected_lang]
                else: title = item["titles"][item["titles"].keys()[0]]+" ["+item["titles"].keys()[0]+"]"
            self.append([item["id"], (" ".join(title.split())), self.data_model.get_item(item["id"])])

class EditTitle(abstract.ListEditor):

    def __init__(self, core, id, widget, data_model):

        self.data_model = data_model
        abstract.ListEditor.__init__(self, id, core, widget=widget, model=gtk.ListStore(str, str, gobject.TYPE_PYOBJECT))
        self.add_sender(id, "update")

        self.widget.append_column(gtk.TreeViewColumn("Language", gtk.CellRendererText(), text=self.COLUMN_LANG))
        self.widget.append_column(gtk.TreeViewColumn("Title", gtk.CellRendererText(), text=self.COLUMN_TEXT))

    def __do(self, widget=None):
        """
        """
        item = None
        buffer = self.title.get_buffer()
        if self.iter and self.get_model() != None: 
            item = self.get_model()[self.iter][self.COLUMN_OBJ]

        retval = self.data_model.edit_title(self.operation, item, self.lang.get_text(), buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter()))
        self.fill()
        self.__dialog_destroy()
        self.emit("update")

    def __dialog_destroy(self, widget=None):
        """
        """
        if self.dialog: 
            self.dialog.destroy()

    def dialog(self, widget, operation):
        """
        """
        self.operation = operation
        builder = gtk.Builder()
        builder.add_from_file("/usr/share/scap-workbench/edit_item.glade")
        self.dialog = builder.get_object("dialog:edit_title")
        self.info_box = builder.get_object("dialog:edit_title:info_box")
        self.lang = builder.get_object("dialog:edit_title:lang")
        self.title = builder.get_object("dialog:edit_title:title")
        builder.get_object("dialog:edit_title:btn_cancel").connect("clicked", self.__dialog_destroy)
        builder.get_object("dialog:edit_title:btn_ok").connect("clicked", self.__do)

        self.core.notify_destroy("notify:not_selected")
        (model, self.iter) = self.get_selection().get_selected()
        if operation == self.data_model.CMD_OPER_ADD:
            pass
        elif operation == self.data_model.CMD_OPER_EDIT:
            if not self.iter:
                self.notifications.append(self.core.notify("Please select at least one item to edit", 2, msg_id="notify:not_selected"))
                return
            else:
                self.lang.set_text(model[self.iter][self.COLUMN_LANG] or "")
                self.title.get_buffer().set_text(model[self.iter][self.COLUMN_TEXT] or "")
        elif operation == self.data_model.CMD_OPER_DEL:
            if not self.iter:
                self.notifications.append(self.core.notify("Please select at least one item to delete", 2, msg_id="notify:not_selected"))
                return
            else: 
                iter = self.dialogDel(self.core.main_window, self.get_selection())
                if iter != None:
                    self.__do()
                return
        else: 
            logger.error("Unknown operation for title dialog: \"%s\"" % (operation,))
            return

        self.dialog.set_transient_for(self.core.main_window)
        self.dialog.show_all()

    def fill(self):
        """
        """
        self.clear()
        for data in self.data_model.get_titles():
            self.append([data.lang, (" ".join(data.text.split())), data])

class EditDescription(abstract.ListEditor):

    def __init__(self, core, id, widget, data_model):

        self.data_model = data_model 
        abstract.ListEditor.__init__(self, id, core, widget=widget, model=gtk.ListStore(str, str, gobject.TYPE_PYOBJECT))
        self.add_sender(id, "update")

        self.widget.append_column(gtk.TreeViewColumn("Language", gtk.CellRendererText(), text=self.COLUMN_LANG))
        self.widget.append_column(gtk.TreeViewColumn("Description", gtk.CellRendererText(), text=self.COLUMN_TEXT))

    def __do(self, widget=None):
        """
        """
        item = None
        buffer = self.description.get_buffer()
        if self.iter and self.get_model() != None: 
            item = self.get_model()[self.iter][self.COLUMN_OBJ]

        retval = self.data_model.edit_description(self.operation, item, self.lang.get_text(), buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter()))
        self.fill()
        self.__dialog_destroy()
        self.emit("update")

    def __dialog_destroy(self, widget=None):
        """
        """
        if self.dialog: 
            self.dialog.destroy()

    def dialog(self, widget, operation):
        """
        """
        self.operation = operation
        builder = gtk.Builder()
        builder.add_from_file("/usr/share/scap-workbench/edit_item.glade")
        self.dialog = builder.get_object("dialog:edit_description")
        self.info_box = builder.get_object("dialog:edit_description:info_box")
        self.lang = builder.get_object("dialog:edit_description:lang")
        self.description = builder.get_object("dialog:edit_description:description")
        builder.get_object("dialog:edit_description:btn_cancel").connect("clicked", self.__dialog_destroy)
        builder.get_object("dialog:edit_description:btn_ok").connect("clicked", self.__do)

        self.core.notify_destroy("notify:not_selected")
        (model, self.iter) = self.get_selection().get_selected()
        if operation == self.data_model.CMD_OPER_ADD:
            pass
        elif operation == self.data_model.CMD_OPER_EDIT:
            if not self.iter:
                self.notifications.append(self.core.notify("Please select at least one item to edit", 2, msg_id="notify:not_selected"))
                return
            else:
                self.lang.set_text(model[self.iter][self.COLUMN_LANG] or "")
                self.description.get_buffer().set_text(model[self.iter][self.COLUMN_TEXT] or "")
        elif operation == self.data_model.CMD_OPER_DEL:
            if not self.iter:
                self.notifications.append(self.core.notify("Please select at least one item to delete", 2, msg_id="notify:not_selected"))
                return
            else: 
                iter = self.dialogDel(self.core.main_window, self.get_selection())
                if iter != None:
                    self.__do()
                return
        else: 
            logger.error("Unknown operation for description dialog: \"%s\"" % (operation,))
            return

        self.dialog.set_transient_for(self.core.main_window)
        self.dialog.show_all()

    def fill(self):

        self.clear()
        for data in self.data_model.get_descriptions():
            self.append([data.lang, re.sub("[\t ]+" , " ", data.text).strip(), data])


class EditWarning(abstract.ListEditor):

    COLUMN_CATEGORY = 3

    def __init__(self, core, id, widget, data_model):
        
        self.data_model = data_model
        abstract.ListEditor.__init__(self, id, core, widget=widget, model=gtk.ListStore(str, str, gobject.TYPE_PYOBJECT, str))
        self.add_sender(id, "update")

        self.widget.append_column(gtk.TreeViewColumn("Language", gtk.CellRendererText(), text=self.COLUMN_LANG))
        self.widget.append_column(gtk.TreeViewColumn("Category", gtk.CellRendererText(), text=self.COLUMN_CATEGORY))
        self.widget.append_column(gtk.TreeViewColumn("Warning", gtk.CellRendererText(), text=self.COLUMN_TEXT))

    def __do(self, widget=None):
        """
        """
        item = None
        category = None
        buffer = self.warning.get_buffer()
        if self.iter and self.get_model() != None: 
            item = self.get_model()[self.iter][self.COLUMN_OBJ]
        if self.category.get_active() != -1:
            category = self.category.get_model()[self.category.get_active()][0]

        retval = self.data_model.edit_warning(self.operation, item, category, self.lang.get_text(), buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter()))
        #if not retval: logger.error("Edit warning: %s warning \"%s:%s:%s\" failed." %(["Adding", "Editing", "Removing"][self.operation], category, 
            #self.lang.get_text(), buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter())))
        self.fill()
        self.__dialog_destroy()
        self.emit("update")

    def __dialog_destroy(self, widget=None):
        """
        """
        if self.dialog: 
            self.dialog.destroy()

    def dialog(self, widget, operation):
        """
        """
        self.operation = operation
        builder = gtk.Builder()
        builder.add_from_file("/usr/share/scap-workbench/edit_item.glade")
        self.dialog = builder.get_object("dialog:edit_warning")
        self.info_box = builder.get_object("dialog:edit_warning:info_box")
        self.lang = builder.get_object("dialog:edit_warning:lang")
        self.warning = builder.get_object("dialog:edit_warning:warning")
        self.category = builder.get_object("dialog:edit_warning:category")
        self.category.set_model(self.combo_model_warning)
        builder.get_object("dialog:edit_warning:btn_cancel").connect("clicked", self.__dialog_destroy)
        builder.get_object("dialog:edit_warning:btn_ok").connect("clicked", self.__do)

        self.core.notify_destroy("notify:not_selected")
        (model, self.iter) = self.get_selection().get_selected()
        if operation == self.data_model.CMD_OPER_ADD:
            pass
        elif operation == self.data_model.CMD_OPER_EDIT:
            if not self.iter:
                self.notifications.append(self.core.notify("Please select at least one item to edit", 2, msg_id="notify:not_selected"))
                return
            else:
                print model[self.iter][self.COLUMN_CATEGORY]
                self.category.set_active(abstract.ENUM_WARNING.pos(model[self.iter][self.COLUMN_OBJ].category) or -1)
                self.lang.set_text(model[self.iter][self.COLUMN_LANG] or "")
                self.warning.get_buffer().set_text(model[self.iter][self.COLUMN_TEXT] or "")
        elif operation == self.data_model.CMD_OPER_DEL:
            if not self.iter:
                self.notifications.append(self.core.notify("Please select at least one item to delete", 2, msg_id="notify:not_selected"))
                return
            else: 
                iter = self.dialogDel(self.core.main_window, self.get_selection())
                if iter != None:
                    self.__do()
                return
        else: 
            logger.error("Unknown operation for description dialog: \"%s\"" % (operation,))
            return

        self.dialog.set_transient_for(self.core.main_window)
        self.dialog.show_all()

    def fill(self):

        self.clear()
        for item in self.data_model.get_warnings():
            category = abstract.ENUM_WARNING.map(item.category)
            index = abstract.ENUM_WARNING.pos(item.category)
            self.append([item.text.lang, item.text.text, item, category[1]])

class EditNotice(abstract.ListEditor):

    COLUMN_ID = 0
    COLUMN_LANG = -1

    def __init__(self, core, id, widget, data_model):

        self.data_model = data_model 
        abstract.ListEditor.__init__(self, id, core, widget=widget, model=gtk.ListStore(str, str, gobject.TYPE_PYOBJECT))
        self.add_sender(id, "update")

        self.widget.append_column(gtk.TreeViewColumn("ID", gtk.CellRendererText(), text=self.COLUMN_ID))
        self.widget.append_column(gtk.TreeViewColumn("Notice", gtk.CellRendererText(), text=self.COLUMN_TEXT))

    def __do(self, widget=None):
        """
        """
        self.core.notify_destroy("notify:dialog_notify")
        # Check input data
        if self.wid.get_text() == "":
            self.core.notify("ID of the notice is mandatory.", 2, info_box=self.info_box, msg_id="notify:dialog_notify")
            self.wid.grab_focus()
            return
        for iter in self.get_model():
            if iter[self.COLUMN_ID] == self.wid.get_text():
                self.core.notify("ID of the notice has to be unique !", 2, info_box=self.info_box, msg_id="notify:dialog_notify")
                self.wid.grab_focus()
                return

        item = None
        buffer = self.notice.get_buffer()
        if self.iter and self.get_model() != None: 
            item = self.get_model()[self.iter][self.COLUMN_OBJ]

        retval = self.data_model.edit_notice(self.operation, item, self.wid.get_text(), buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter()))
        self.fill()
        self.__dialog_destroy()
        self.emit("update")

    def __dialog_destroy(self, widget=None):
        """
        """
        if self.dialog: 
            self.dialog.destroy()

    def dialog(self, widget, operation):
        """
        """
        self.operation = operation
        builder = gtk.Builder()
        builder.add_from_file("/usr/share/scap-workbench/edit_item.glade")
        self.dialog = builder.get_object("dialog:edit_notice")
        self.info_box = builder.get_object("dialog:edit_notice:info_box")
        self.wid = builder.get_object("dialog:edit_notice:id")
        self.notice = builder.get_object("dialog:edit_notice:notice")
        builder.get_object("dialog:edit_notice:btn_cancel").connect("clicked", self.__dialog_destroy)
        builder.get_object("dialog:edit_notice:btn_ok").connect("clicked", self.__do)

        self.core.notify_destroy("notify:not_selected")
        (model, self.iter) = self.get_selection().get_selected()
        if operation == self.data_model.CMD_OPER_ADD:
            pass
        elif operation == self.data_model.CMD_OPER_EDIT:
            if not self.iter:
                self.notifications.append(self.core.notify("Please select at least one item to edit", 2, msg_id="notify:not_selected"))
                return
            else:
                self.wid.set_text(model[self.iter][self.COLUMN_ID] or "")
                self.notice.get_buffer().set_text(model[self.iter][self.COLUMN_TEXT] or "")
        elif operation == self.data_model.CMD_OPER_DEL:
            if not self.iter:
                self.notifications.append(self.core.notify("Please select at least one item to delete", 2, msg_id="notify:not_selected"))
                return
            else: 
                iter = self.dialogDel(self.core.main_window, self.get_selection())
                if iter != None:
                    self.__do()
                return
        else: 
            logger.error("Unknown operation for description dialog: \"%s\"" % (operation,))
            return

        self.dialog.set_transient_for(self.core.main_window)
        self.dialog.show_all()

    def fill(self):

        self.get_model().clear()
        for data in self.data_model.get_notices():
            self.append([data.id, re.sub("[\t ]+" , " ", data.text.text or "").strip(), data])

class EditStatus(abstract.ListEditor):

    COLUMN_DATE = 0

    def __init__(self, core, id, widget, data_model):

        self.data_model = data_model 
        abstract.ListEditor.__init__(self, id, core, widget=widget, model=gtk.ListStore(str, str, gobject.TYPE_PYOBJECT))
        self.add_sender(id, "update")

        self.widget.append_column(gtk.TreeViewColumn("Date", gtk.CellRendererText(), text=self.COLUMN_DATE))
        self.widget.append_column(gtk.TreeViewColumn("Status", gtk.CellRendererText(), text=self.COLUMN_TEXT))

    def __do(self, widget=None):
        """
        """
        self.core.notify_destroy("notify:dialog_notify")
        # Check input data
        if self.status.get_active() == -1:
            self.core.notify("Status has to be choosen.", 2, info_box=self.info_box, msg_id="notify:dialog_notify")
            self.status.grab_focus()
            return

        item = None
        if self.iter and self.get_model() != None: 
            item = self.get_model()[self.iter][self.COLUMN_OBJ]

        year, month, day = self.calendar.get_date()
        retval = self.data_model.edit_status(self.operation, item, "%s-%s-%s" % (year, month, day), self.status.get_active())
        self.fill()
        self.__dialog_destroy()
        self.emit("update")

    def __dialog_destroy(self, widget=None):
        """
        """
        if self.dialog: 
            self.dialog.destroy()

    def dialog(self, widget, operation):
        """
        """
        self.operation = operation
        builder = gtk.Builder()
        builder.add_from_file("/usr/share/scap-workbench/edit_item.glade")
        self.dialog = builder.get_object("dialog:edit_status")
        self.info_box = builder.get_object("dialog:edit_status:info_box")
        self.calendar = builder.get_object("dialog:edit_status:calendar")
        self.status = builder.get_object("dialog:edit_status:status")
        self.status.set_model(self.combo_model_status)
        builder.get_object("dialog:edit_status:btn_cancel").connect("clicked", self.__dialog_destroy)
        builder.get_object("dialog:edit_status:btn_ok").connect("clicked", self.__do)

        self.core.notify_destroy("notify:not_selected")
        (model, self.iter) = self.get_selection().get_selected()
        if operation == self.data_model.CMD_OPER_ADD:
            day, month, year = time.strftime("%d %m %Y", time.gmtime()).split()
            self.calendar.select_month(int(month), int(year))
            self.calendar.select_day(int(day))
        elif operation == self.data_model.CMD_OPER_EDIT:
            if not self.iter:
                self.notifications.append(self.core.notify("Please select at least one item to edit", 2, msg_id="notify:not_selected"))
                return
            else:
                day, month, year = time.strftime("%d %m %Y", time.localtime(model[self.iter][self.COLUMN_OBJ].date)).split()
                self.calendar.select_month(int(month), int(year))
                self.calendar.select_day(int(day))
                self.status.set_active(abstract.ENUM_STATUS_CURRENT.pos(model[self.iter][self.COLUMN_OBJ].status) or -1)
        elif operation == self.data_model.CMD_OPER_DEL:
            if not self.iter:
                self.notifications.append(self.core.notify("Please select at least one item to delete", 2, msg_id="notify:not_selected"))
                return
            else: 
                iter = self.dialogDel(self.core.main_window, self.get_selection())
                if iter != None:
                    self.__do()
                return
        else: 
            logger.error("Unknown operation for description dialog: \"%s\"" % (operation,))
            return

        self.dialog.set_transient_for(self.core.main_window)
        self.dialog.show_all()

    def fill(self):

        self.clear()
        for item in self.data_model.get_statuses():
            status = abstract.ENUM_STATUS_CURRENT.map(item.status)
            index = abstract.ENUM_STATUS_CURRENT.pos(item.status)
            self.append([time.strftime("%d-%m-%Y", time.localtime(item.date)), status[1], item])

class EditIdent(commands.DHEditItems,abstract.ControlEditWindow):

    COLUMN_ID = 0
    COLUMN_SYSTEM = 1
    COLUMN_OBJECTS = 2

    def __init__(self, core, builder):

        #set listView and model
        lv = builder.get_object("edit:dependencies:lv_ident")
        self.box_ident = builder.get_object("edit:dependencies:box_ident")
        model = gtk.ListStore(str, str, gobject.TYPE_PYOBJECT)
        lv.set_model(model)
        
        #information for new/edit dialog
        values = {
                        "name_dialog":  "Edit Question",
                        "view":         lv,
                        "cb":           self.DHEditIdent,
                        "textEntry":    {"name":    "ID",
                                        "column":   self.COLUMN_ID,
                                        "empty":    False, 
                                        "unique":   True},
                        "textView":     {"name":    "System",
                                        "column":   self.COLUMN_SYSTEM,
                                        "empty":    False, 
                                        "unique":   False},
                        }

        abstract.ControlEditWindow.__init__(self, core, lv, values)
        btn_add = builder.get_object("edit:dependencies:btn_ident_add")
        btn_edit = builder.get_object("edit:dependencies:btn_ident_edit")
        btn_del = builder.get_object("edit:dependencies:btn_ident_del")
        
        # set callBack
        btn_add.connect("clicked", self.cb_add_row)
        btn_edit.connect("clicked", self.cb_edit_row)
        btn_del.connect("clicked", self.cb_del_row)

        self.addColumn("ID",self.COLUMN_ID)
        self.addColumn("System",self.COLUMN_SYSTEM)

    def fill(self, item):
        self.item = item
        self.model.clear()
        if item:
            self.item = item.to_rule()
            for data in self.item.idents:
                self.model.append([data.id, data.system, data])
                
    def set_sensitive(self, sensitive):
        self.box_ident.set_sensitive(sensitive)

class EditQuestion(abstract.ListEditor):

    COLUMN_OVERRIDE = 3
    
    def __init__(self, core, id, widget, data_model):

        self.data_model = data_model 
        abstract.ListEditor.__init__(self, id, core, widget=widget, model=gtk.ListStore(str, str, gobject.TYPE_PYOBJECT, bool))
        self.add_sender(id, "update")

        self.widget.append_column(gtk.TreeViewColumn("Language", gtk.CellRendererText(), text=self.COLUMN_LANG))
        self.widget.append_column(gtk.TreeViewColumn("Override", gtk.CellRendererText(), text=self.COLUMN_OVERRIDE))
        self.widget.append_column(gtk.TreeViewColumn("Question", gtk.CellRendererText(), text=self.COLUMN_TEXT))

    def __do(self, widget=None):
        """
        """
        item = None
        buffer = self.question.get_buffer()
        if self.iter and self.get_model() != None: 
            item = self.get_model()[self.iter][self.COLUMN_OBJ]

        retval = self.data_model.edit_question(self.operation, item, self.lang.get_text(), self.override.get_active(), buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter()))
        self.fill()
        self.__dialog_destroy()
        self.emit("update")

    def __dialog_destroy(self, widget=None):
        """
        """
        if self.dialog: 
            self.dialog.destroy()

    def dialog(self, widget, operation):
        """
        """
        self.operation = operation
        builder = gtk.Builder()
        builder.add_from_file("/usr/share/scap-workbench/edit_item.glade")
        self.dialog = builder.get_object("dialog:edit_question")
        self.info_box = builder.get_object("dialog:edit_question:info_box")
        self.lang = builder.get_object("dialog:edit_question:lang")
        self.question = builder.get_object("dialog:edit_question:question")
        self.override = builder.get_object("dialog:edit_question:override")
        builder.get_object("dialog:edit_question:btn_cancel").connect("clicked", self.__dialog_destroy)
        builder.get_object("dialog:edit_question:btn_ok").connect("clicked", self.__do)

        self.core.notify_destroy("notify:not_selected")
        (model, self.iter) = self.get_selection().get_selected()
        if operation == self.data_model.CMD_OPER_ADD:
            pass
        elif operation == self.data_model.CMD_OPER_EDIT:
            if not self.iter:
                self.notifications.append(self.core.notify("Please select at least one item to edit", 2, msg_id="notify:not_selected"))
                return
            else:
                self.lang.set_text(model[self.iter][self.COLUMN_LANG] or "")
                self.override.set_active(model[self.iter][self.COLUMN_OVERRIDE])
                self.question.get_buffer().set_text(model[self.iter][self.COLUMN_TEXT] or "")
        elif operation == self.data_model.CMD_OPER_DEL:
            if not self.iter:
                self.notifications.append(self.core.notify("Please select at least one item to delete", 2, msg_id="notify:not_selected"))
                return
            else: 
                iter = self.dialogDel(self.core.main_window, self.get_selection())
                if iter != None:
                    self.__do()
                return
        else: 
            logger.error("Unknown operation for question dialog: \"%s\"" % (operation,))
            return

        self.dialog.set_transient_for(self.core.main_window)
        self.dialog.show_all()

    def fill(self):

        self.clear()
        for data in self.data_model.get_questions():
            self.append([data.lang, re.sub("[\t ]+" , " ", data.text).strip(), data, data.overrides])


class EditRationale(abstract.ListEditor):

    COLUMN_OVERRIDE = 3
    
    def __init__(self, core, id, widget, data_model):

        self.data_model = data_model 
        abstract.ListEditor.__init__(self, id, core, widget=widget, model=gtk.ListStore(str, str, gobject.TYPE_PYOBJECT, bool))
        self.add_sender(id, "update")

        self.widget.append_column(gtk.TreeViewColumn("Language", gtk.CellRendererText(), text=self.COLUMN_LANG))
        self.widget.append_column(gtk.TreeViewColumn("Override", gtk.CellRendererText(), text=self.COLUMN_OVERRIDE))
        self.widget.append_column(gtk.TreeViewColumn("Rationale", gtk.CellRendererText(), text=self.COLUMN_TEXT))

    def __do(self, widget=None):
        """
        """
        item = None
        buffer = self.rationale.get_buffer()
        if self.iter and self.get_model() != None: 
            item = self.get_model()[self.iter][self.COLUMN_OBJ]

        retval = self.data_model.edit_rationale(self.operation, item, self.lang.get_text(), self.override.get_active(), buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter()))
        self.fill()
        self.__dialog_destroy()
        self.emit("update")

    def __dialog_destroy(self, widget=None):
        """
        """
        if self.dialog: 
            self.dialog.destroy()

    def dialog(self, widget, operation):
        """
        """
        self.operation = operation
        builder = gtk.Builder()
        builder.add_from_file("/usr/share/scap-workbench/edit_item.glade")
        self.dialog = builder.get_object("dialog:edit_rationale")
        self.info_box = builder.get_object("dialog:edit_rationale:info_box")
        self.lang = builder.get_object("dialog:edit_rationale:lang")
        self.rationale = builder.get_object("dialog:edit_rationale:rationale")
        self.override = builder.get_object("dialog:edit_rationale:override")
        builder.get_object("dialog:edit_rationale:btn_cancel").connect("clicked", self.__dialog_destroy)
        builder.get_object("dialog:edit_rationale:btn_ok").connect("clicked", self.__do)

        self.core.notify_destroy("notify:not_selected")
        (model, self.iter) = self.get_selection().get_selected()
        if operation == self.data_model.CMD_OPER_ADD:
            pass
        elif operation == self.data_model.CMD_OPER_EDIT:
            if not self.iter:
                self.notifications.append(self.core.notify("Please select at least one item to edit", 2, msg_id="notify:not_selected"))
                return
            else:
                self.lang.set_text(model[self.iter][self.COLUMN_LANG] or "")
                self.override.set_active(model[self.iter][self.COLUMN_OVERRIDE])
                self.rationale.get_buffer().set_text(model[self.iter][self.COLUMN_TEXT] or "")
        elif operation == self.data_model.CMD_OPER_DEL:
            if not self.iter:
                self.notifications.append(self.core.notify("Please select at least one item to delete", 2, msg_id="notify:not_selected"))
                return
            else: 
                iter = self.dialogDel(self.core.main_window, self.get_selection())
                if iter != None:
                    self.__do()
                return
        else: 
            logger.error("Unknown operation for rationale dialog: \"%s\"" % (operation,))
            return

        self.dialog.set_transient_for(self.core.main_window)
        self.dialog.show_all()

    def fill(self):

        self.clear()
        for data in self.data_model.get_rationales():
            self.append([data.lang, re.sub("[\t ]+" , " ", data.text).strip(), data, data.overrides])


class EditPlatform(commands.DHEditItems,abstract.ControlEditWindow):

    COLUMN_TEXT = 0
    COLUMN_OBJECTS = 1

    def __init__(self, core, builder):

        #set listView and model
        lv = builder.get_object("edit:dependencies:lv_platform")
        model = gtk.ListStore(str, gobject.TYPE_PYOBJECT)
        lv.set_model(model)
        
        #information for new/edit dialog
        values = {
                        "name_dialog":  "Edit Platform",
                        "view":         lv,
                        "cb":           self.DHEditPlatform,
                        "textView":     {"name":    "Platform",
                                        "column":   self.COLUMN_TEXT,
                                        "empty":    False, 
                                        "unique":   False,
                                        "init_data": ""}
                        }

        abstract.ControlEditWindow.__init__(self, core, lv, values)
        btn_add = builder.get_object("edit:dependencies:btn_platform_add")
        btn_edit = builder.get_object("edit:dependencies:btn_platform_edit")
        btn_del = builder.get_object("edit:dependencies:btn_platform_del")
        
        # set callBack
        btn_add.connect("clicked", self.cb_add_row)
        btn_edit.connect("clicked", self.cb_edit_row)
        btn_del.connect("clicked", self.cb_del_row)

        self.addColumn("Platform CPE",self.COLUMN_TEXT)

    def fill(self, item):
        self.item = item
        self.model.clear()
        if item:
            for data in item.platforms:
                self.model.append([data, data])

#======================================= EDIT VALUES ==========================================

class EditValues(abstract.MenuButton, abstract.ControlEditWindow):
    
    COLUMN_ID = 0
    COLUMN_TITLE = 1
    COLUMN_TYPE_ITER = 2
    COLUMN_TYPE_TEXT = 3
    COLUMN_OBJECT = 4
    COLUMN_CHECK = 5
    COLUMN_CHECK_EXPORT = 6
    
    def __init__(self, core, id, builder):

        self.data_model = commands.DHValues(core) 
        self.core = core
        self.builder = builder
        self.id = id

        EventObject.__init__(self, core)
        self.core.register(self.id, self)
        self.add_sender(id, "update")
        
        #edit data of values
        # -- VALUES --
        self.values = builder.get_object("edit:values")

        # -- TITLE --
        self.titles = EditTitle(self.core, "gui:edit:xccdf:values:titles", builder.get_object("edit:values:titles"), self.data_model)
        self.builder.get_object("edit:values:titles:btn_add").connect("clicked", self.titles.dialog, self.data_model.CMD_OPER_ADD)
        self.builder.get_object("edit:values:titles:btn_edit").connect("clicked", self.titles.dialog, self.data_model.CMD_OPER_EDIT)
        self.builder.get_object("edit:values:titles:btn_del").connect("clicked", self.titles.dialog, self.data_model.CMD_OPER_DEL)

        # -- DESCRIPTION --
        self.descriptions = EditDescription(self.core, "gui:edit:xccdf:values:descriptions", builder.get_object("edit:values:descriptions"), self.data_model)
        self.builder.get_object("edit:values:descriptions:btn_add").connect("clicked", self.descriptions.dialog, self.data_model.CMD_OPER_ADD)
        self.builder.get_object("edit:values:descriptions:btn_edit").connect("clicked", self.descriptions.dialog, self.data_model.CMD_OPER_EDIT)
        self.builder.get_object("edit:values:descriptions:btn_del").connect("clicked", self.descriptions.dialog, self.data_model.CMD_OPER_DEL)
        self.builder.get_object("edit:values:descriptions:btn_preview").connect("clicked", self.descriptions.preview)

        # -- WARNING --
        self.warnings = EditWarning(self.core, "gui:edit:xccdf:values:warnings", builder.get_object("edit:values:warnings"), self.data_model)
        builder.get_object("edit:values:warnings:btn_add").connect("clicked", self.warnings.dialog, self.data_model.CMD_OPER_ADD)
        builder.get_object("edit:values:warnings:btn_edit").connect("clicked", self.warnings.dialog, self.data_model.CMD_OPER_EDIT)
        builder.get_object("edit:values:warnings:btn_del").connect("clicked", self.warnings.dialog, self.data_model.CMD_OPER_DEL)

        # -- STATUS --
        self.statuses = EditStatus(self.core, "gui:edit:xccdf:values:statuses", builder.get_object("edit:values:statuses"), self.data_model)
        builder.get_object("edit:values:statuses:btn_add").connect("clicked", self.statuses.dialog, self.data_model.CMD_OPER_ADD)
        builder.get_object("edit:values:statuses:btn_edit").connect("clicked", self.statuses.dialog, self.data_model.CMD_OPER_EDIT)
        builder.get_object("edit:values:statuses:btn_del").connect("clicked", self.statuses.dialog, self.data_model.CMD_OPER_DEL)

        # -- QUESTIONS --
        self.questions = EditQuestion(self.core, "gui:edit:xccdf:values:questions", builder.get_object("edit:values:questions"), self.data_model)
        builder.get_object("edit:values:questions:btn_add").connect("clicked", self.questions.dialog, self.data_model.CMD_OPER_ADD)
        builder.get_object("edit:values:questions:btn_edit").connect("clicked", self.questions.dialog, self.data_model.CMD_OPER_EDIT)
        builder.get_object("edit:values:questions:btn_del").connect("clicked", self.questions.dialog, self.data_model.CMD_OPER_DEL)

        # -- VALUES --
        self.values_values = EditValuesValues(self.core, "gui:edit:xccdf:values:values", builder.get_object("edit:values:values"), self.data_model)
        builder.get_object("edit:values:values:btn_add").connect("clicked", self.values_values.dialog, self.data_model.CMD_OPER_ADD)
        builder.get_object("edit:values:values:btn_edit").connect("clicked", self.values_values.dialog, self.data_model.CMD_OPER_EDIT)
        builder.get_object("edit:values:values:btn_del").connect("clicked", self.values_values.dialog, self.data_model.CMD_OPER_DEL)
        # -------------
        
        self.vid = self.builder.get_object("edit:values:id")
        self.version = self.builder.get_object("edit:values:version")
        self.version.connect("focus-out-event", self.__change)
        self.version.connect("key-press-event", self.__change)
        self.version_time = self.builder.get_object("edit:values:version_time")
        self.version_time.connect("focus-out-event", self.__change)
        self.version_time.connect("key-press-event", self.__change)
        self.cluster_id = self.builder.get_object("edit:values:cluster_id")
        self.cluster_id.connect("focus-out-event", self.__change)
        self.cluster_id.connect("key-press-event", self.__change)
        self.vtype = self.builder.get_object("edit:values:type")
        self.operator = self.builder.get_object("edit:values:operator")
        self.operator.connect("changed", self.__change)
        self.abstract = self.builder.get_object("edit:values:abstract")
        self.abstract.connect("toggled", self.__change)
        self.prohibit_changes = self.builder.get_object("edit:values:prohibit_changes")
        self.prohibit_changes.connect("toggled", self.__change)
        self.interactive = self.builder.get_object("edit:values:interactive")
        self.interactive.connect("toggled", self.__change)

        self.operator.set_model(abstract.Enum_type.combo_model_operator_number)
        
    def show(self, active):
        self.values.set_sensitive(active)
        self.values.set_visible(active)

    def update(self):
        self.__update()

    def __change(self, widget, event=None):

        if event and event.type == gtk.gdk.KEY_PRESS and event.keyval != gtk.keysyms.Return:
            return

        if widget == self.version:
            self.data_model.edit_value(version=widget.get_text())
        elif widget == self.version_time:
            timestamp = self.controlDate(widget.get_text())
            if timestamp:
                self.data_model.update(version_time=timestamp)
        elif widget == self.cluster_id:
            self.data_model.edit_value(cluster_id=widget.get_text())
        elif widget == self.operator:
            self.data_model.edit_value(operator=abstract.ENUM_OPERATOR[widget.get_active()][0])
        elif widget == self.abstract:
            self.data_model.edit_value(abstract=widget.get_active())
        elif widget == self.prohibit_changes:
            self.data_model.edit_value(prohibit_changes=widget.get_active())
        elif widget == self.interactive:
            self.data_model.edit_value(interactive=widget.get_active())
        else: 
            logger.error("Change: not supported object in \"%s\"" % (widget,))
            return

    def __clear(self):
        self.titles.clear()
        self.descriptions.clear()
        self.warnings.clear()
        self.statuses.clear()
        self.questions.clear()
        self.values_values.clear()
        self.operator.set_active(-1)
        self.interactive.set_active(False)
        self.vtype.set_text("")

    def __update(self):

        details = self.data_model.get_item_details(self.core.selected_item)

        self.values.set_sensitive(details != None)

        if details:

            """It depends on value type what details should
            be filled and sensitive to user actions"""
            # TODO

            self.vid.set_text(details["id"] or "")
            self.version.set_text(details["version"] or "")
            self.version_time.set_text(details["version_time"] or "")
            self.cluster_id.set_text(details["cluster_id"] or "")
            self.vtype.set_text(abstract.ENUM_TYPE.map(details["vtype"])[1])
            self.abstract.set_active(details["abstract"])
            self.prohibit_changes.set_active(details["prohibit_changes"])
            self.interactive.set_active(details["interactive"])
            self.operator.set_active(abstract.ENUM_OPERATOR.pos(details["oper"]))
            self.titles.fill()
            self.descriptions.fill()
            self.warnings.fill()
            self.statuses.fill()
            self.questions.fill()
            self.values_values.fill()

    def cb_combo_value_operator(self,widget):
        COLUMN_DATA = 0
        (model,iter) = self.selection.get_selected()
        if iter:
            value = model.get_value(iter, self.COLUMN_OBJECT)
            active = widget.get_active()
            if active > 0:
                combo_model = widget.get_model()
                self.DHEditValueOper(value, combo_model[active][COLUMN_DATA])
        else:
            logger.error("Error: Not select value.")
            
    def cb_combo_value_interactive(self,widget):
        COLUMN_DATA = 0
        (model,iter) = self.selection.get_selected()
        if iter:
            self.value_nbook.set_sensitive(True)
            value = model.get_value(iter, self.COLUMN_OBJECT)
            self.DHChBoxValueInteractive(value, widget.get_active())
        else:
            logger.error("Error: Not select value.")

    def cb_match(self, widget, event):

        vys = self.DHEditBoundMatch(self.value_akt, None, None, widget.get_text())
        if not vys:
            logger.error("Not changed value match")
        else:
            self.emit("item_changed")
            
    def cb_control_bound(self, widget, event, type):
        
        if widget.get_text() == "":
            data = "nan"
        else:
            data = widget.get_text()
            
        try:
            data = float(data)
        except:
            self.dialogInfo("Invalid number in %s bound." % (type), self.core.main_window)
            if self.selector_empty:
                if type == "lower":
                    if str(self.selector_empty.get_lower_bound()) != "nan":
                        widget.set_text(str(self.selector_empty.get_lower_bound()))
                    else:
                        widget.set_text("")
                else:
                    if str(self.selector_empty.get_upper_bound()) != "nan":
                        widget.set_text(str(self.selector_empty.get_upper_bound()))
                    else:
                        widget.set_text("")
            else:
                widget.set_text("")
            return

        upper = self.text_upper_bound.get_text()
        lower = self.text_lower_bound.get_text()

        if upper != "" and upper != "nan" and lower != "" and lower != "nan":
            if lower >= upper:
                self.dialogInfo("Upper bound must be greater then lower bound.", self.core.main_window)
                if self.selector_empty:
                    if type == "lower":
                        if str(self.selector_empty.get_lower_bound()) != "nan":
                            widget.set_text(str(self.selector_empty.get_lower_bound()))
                    else:
                        if str(self.selector_empty.get_upper_bound()) != "nan":
                            widget.set_text(str(self.selector_empty.get_upper_bound()))
                else:
                    widget.set_text("")
                return
        #add bound
        if type == "upper":
            vys = self.DHEditBoundMatch(self.value_akt, data, None, None)
        else:
            vys = self.DHEditBoundMatch(self.value_akt, None, data, None)
        
        if not vys:
            logger.error("Not changed value bound.")
        else:
            self.emit("item_changed")

class EditValuesValues(abstract.ListEditor):

    COLUMN_SELECTOR     = 0
    COLUMN_VALUE        = 1
    COLUMN_DEFAULT      = 2
    COLUMN_LOWER_BOUND  = 3
    COLUMN_UPPER_BOUND  = 4
    COLUMN_MUST_MATCH   = 5
    COLUMN_MATCH        = 6
    COLUMN_OBJ          = 7
    
    def __init__(self, core, id, widget, data_model):

        self.data_model = data_model 
        abstract.ListEditor.__init__(self, id, core, widget=widget, model=gtk.ListStore(str, str, str, str, str, bool, str, gobject.TYPE_PYOBJECT))
        self.add_sender(id, "update")

        self.widget.append_column(gtk.TreeViewColumn("Selector", gtk.CellRendererText(), text=self.COLUMN_SELECTOR))
        self.widget.append_column(gtk.TreeViewColumn("Value", gtk.CellRendererText(), text=self.COLUMN_VALUE))
        self.widget.append_column(gtk.TreeViewColumn("Default", gtk.CellRendererText(), text=self.COLUMN_DEFAULT))
        self.widget.append_column(gtk.TreeViewColumn("Lower bound", gtk.CellRendererText(), text=self.COLUMN_LOWER_BOUND))
        self.widget.append_column(gtk.TreeViewColumn("Upper bound", gtk.CellRendererText(), text=self.COLUMN_UPPER_BOUND))
        self.widget.append_column(gtk.TreeViewColumn("Must match", gtk.CellRendererText(), text=self.COLUMN_MUST_MATCH))
        self.widget.append_column(gtk.TreeViewColumn("Match", gtk.CellRendererText(), text=self.COLUMN_MATCH))

    def __do(self, widget=None):
        """
        """
        # Check input data
        (model, iter) = self.get_selection().get_selected()
        item = None
        if iter:
            item = model[iter][self.COLUMN_OBJ]

        for inst in model:
            if self.selector.get_text() == inst[0] and model[iter][self.COLUMN_SELECTOR] != self.selector.get_text():
                self.core.notify("Selector \"%s\" is already used !" % (inst[0],), 2, self.info_box, msg_id="dialog:add_value")
                self.selector.grab_focus()
                self.selector.modify_base(gtk.STATE_NORMAL, gtk.gdk.Color("#FFC1C2"))
                return
        self.selector.modify_base(gtk.STATE_NORMAL, self.__entry_style)
        
        if self.type == openscap.OSCAP.XCCDF_TYPE_BOOLEAN:
            self.data_model.edit_value_of_value(self.operation, item, self.selector.get_text(), self.value_bool.get_active(), self.default_bool.get_active(), 
                        self.match.get_text(), None, None, self.must_match.get_active())
        if self.type == openscap.OSCAP.XCCDF_TYPE_NUMBER:
            self.data_model.edit_value_of_value(self.operation, item, self.selector.get_text(), self.value.get_text(), self.default.get_text(), self.match.get_text(), 
                        self.upper_bound.get_text(), self.lower_bound.get_value_as_int(), self.must_match.get_value_as_int())
        else: self.data_model.edit_value_of_value(self.operation, item, self.selector.get_text(), self.value.get_text(), self.default.get_text(), self.match.get_text(), None,
                            None, self.must_match.get_active())
        self.fill()
        self.__dialog_destroy()
        self.emit("update")

    def __dialog_destroy(self, widget=None):
        """
        """
        if self.dialog: 
            self.dialog.destroy()

    def dialog(self, widget, operation):
        """
        """
        self.operation = operation
        builder = gtk.Builder()
        builder.add_from_file("/usr/share/scap-workbench/edit_item.glade")
        self.dialog = builder.get_object("dialog:edit_value")
        self.info_box = builder.get_object("dialog:edit_value:info_box")
        self.selector = builder.get_object("dialog:edit_value:selector")
        self.value = builder.get_object("dialog:edit_value:value")
        self.value_bool = builder.get_object("dialog:edit_value:value:bool")
        self.default = builder.get_object("dialog:edit_value:default")
        self.default_bool = builder.get_object("dialog:edit_value:default:bool")
        self.match = builder.get_object("dialog:edit_value:match")
        self.upper_bound = builder.get_object("dialog:edit_value:upper_bound")
        self.lower_bound = builder.get_object("dialog:edit_value:lower_bound")
        self.must_match = builder.get_object("dialog:edit_value:must_match")
        builder.get_object("dialog:edit_value:btn_cancel").connect("clicked", self.__dialog_destroy)
        builder.get_object("dialog:edit_value:btn_ok").connect("clicked", self.__do)

        self.__entry_style = self.selector.get_style().base[gtk.STATE_NORMAL]

        # Upper and lower bound should be disabled if value is not a number
        item = self.data_model.get_item_details(self.core.selected_item)
        self.type = item["vtype"]
        if self.type != openscap.OSCAP.XCCDF_TYPE_NUMBER:
            self.upper_bound.set_sensitive(False)
            self.lower_bound.set_sensitive(False)

        # Different widgets for different type boolean or other
        boolean = (self.type == openscap.OSCAP.XCCDF_TYPE_BOOLEAN)
        self.value.set_visible(not boolean)
        self.default.set_visible(not boolean)
        self.value_bool.set_visible(boolean)
        self.default_bool.set_visible(boolean)

        self.core.notify_destroy("notify:not_selected")
        (model, iter) = self.get_selection().get_selected()
        if operation == self.data_model.CMD_OPER_ADD:
            pass
        elif operation == self.data_model.CMD_OPER_EDIT:
            if not iter:
                self.notifications.append(self.core.notify("Please select at least one item to edit", 2, msg_id="notify:not_selected"))
                return
            else:
                self.selector.set_text(model[iter][self.COLUMN_SELECTOR] or "")
                self.value.set_text(model[iter][self.COLUMN_VALUE] or "")
                self.default.set_text(model[iter][self.COLUMN_DEFAULT] or "")
                self.match.set_text(model[iter][self.COLUMN_MATCH] or "")
                self.upper_bound.set_text(model[iter][self.COLUMN_UPPER_BOUND] or "")
                self.lower_bound.set_text(model[iter][self.COLUMN_LOWER_BOUND] or "")
                self.must_match.set_active(model[iter][self.COLUMN_MUST_MATCH])
        elif operation == self.data_model.CMD_OPER_DEL:
            if not iter:
                self.notifications.append(self.core.notify("Please select at least one item to delete", 2, msg_id="notify:not_selected"))
                return
            else: 
                iter = self.dialogDel(self.core.main_window, self.get_selection())
                if iter != None:
                    self.__do()
                return
        else: 
            logger.error("Unknown operation for values dialog: \"%s\"" % (operation,))
            return

        self.dialog.set_transient_for(self.core.main_window)
        self.dialog.show()

    def fill(self):

        self.clear()
        for instance in self.data_model.get_value_instances():
            self.append([instance["selector"], 
                         instance["value"], 
                         instance["defval"], 
                         instance["lower_bound"], 
                         instance["upper_bound"], 
                         instance["must_match"], 
                         instance["match"], 
                         instance["item"]])

#======================================= EDIT FIXTEXT ==========================================

class EditFixtext(abstract.ListEditor):
    
    COLUMN_TEXT = 0

    def __init__(self, core, builder):
        
        self.core = core
        self.builder = builder
        self.data_model = commands.DHEditItems(core)
        abstract.ListEditor.__init__(self, "gui:edit:items:operations:fixtext", self.core, widget=self.builder.get_object("edit:operations:lv_fixtext"), model=gtk.ListStore(str, gobject.TYPE_PYOBJECT))
        self.builder.get_object("edit:operations:btn_fixtext_preview").connect("clicked", self.preview)
        
        # Register Event Object
        self.add_sender(self.id, "item_changed")
        self.edit_fixtext_option = EditFixtextOption(core, builder)
        self.add_receiver("gui:edit:items:operations:fixtext", "item_changed", self.__update)
        
        #information for new/edit dialog
        values = {
                    "name_dialog":  "Fixtext",
                    "view":         self,
                    "cb":           self.data_model.DHEditFixtextText,
                    "textView":     {"name":    "Value",
                                    "column":   0,
                                    "empty":    False, 
                                    "unique":   False}
                        }
        btn_add = builder.get_object("edit:operations:btn_fixtext_add")
        btn_edit = builder.get_object("edit:operations:btn_fixtext_edit")
        btn_del = builder.get_object("edit:operations:btn_fixtext_del")
        
        # set callBack to btn
        btn_add.connect("clicked", self.cb_add_row, values)
        btn_edit.connect("clicked", self.cb_edit_row, values)
        btn_del.connect("clicked", self.cb_del_row, values)
        
        self.widget.get_selection().connect("changed", self.__cb_item_changed, self.widget)
        
        self.box_main = self.builder.get_object("edit:operations:fixtext:box")
        
        self.widget.append_column(gtk.TreeViewColumn("Text", gtk.CellRendererText(), text=0))
        
    def fill(self, item):
        self.clear()
        self.emit("item_changed")
        if item:
            self.item = item
            rule = item.to_rule()
            if rule.fixtexts:
                for obj in rule.fixtexts:
                    self.append([re.sub("[\t ]+" , " ", obj.text.text).strip(), obj])
        else:
            self.item = None
    
    def set_sensitive(self, sensitive):
        self.box_main.set_sensitive(sensitive)
        
    def __cb_item_changed(self, widget, treeView):
        self.emit("item_changed")
        treeView.columns_autosize()
    
    def __update(self):
        (model,iter) = self.get_selection().get_selected()
 
        if iter:
            self.edit_fixtext_option.fill(model.get_value(iter, 1))
        else:
            self.edit_fixtext_option.fill(None)

            
class EditFixtextOption(commands.DHEditItems,abstract.ControlEditWindow):
    
    def __init__(self, core, builder):
    
        # set  models
        self.core = core
        self.builder = builder
        abstract.ControlEditWindow.__init__(self, core, None, None)
        
        #edit data of fictext
        self.entry_reference = self.builder.get_object("edit:operations:fixtext:entry_reference1")
        self.entry_reference.connect("focus-out-event",self.cb_entry_fixtext_reference)
        
        self.combo_strategy = self.builder.get_object("edit:operations:fixtext:combo_strategy1")
        self.set_model_to_comboBox(self.combo_strategy,self.combo_model_strategy, self.COMBO_COLUMN_VIEW)
        self.combo_strategy.connect( "changed", self.cb_combo_fixtext_strategy)
        
        self.combo_complexity = self.builder.get_object("edit:operations:fixtext:combo_complexity1")
        self.set_model_to_comboBox(self.combo_complexity,self.combo_model_level, self.COMBO_COLUMN_VIEW)
        self.combo_complexity.connect( "changed", self.cb_combo_fixtext_complexity)
    
        self.combo_disruption = self.builder.get_object("edit:operations:fixtext:combo_disruption1")
        self.set_model_to_comboBox(self.combo_disruption,self.combo_model_level, self.COMBO_COLUMN_VIEW)
        self.combo_disruption.connect( "changed", self.cb_combo_fixtext_disruption)
    
        self.chbox_reboot = self.builder.get_object("edit:operations:fixtext:chbox_reboot1")
        self.chbox_reboot.connect("toggled",self.cb_chbox_fixtext_reboot)

        self.box_detail= self.builder.get_object("edit:operations:fixtext:frame")
        
    def fill(self, fixtext):
        self.item = fixtext
        self.combo_strategy.handler_block_by_func(self.cb_combo_fixtext_strategy)
        self.combo_complexity.handler_block_by_func(self.cb_combo_fixtext_complexity)
        self.combo_disruption.handler_block_by_func(self.cb_combo_fixtext_disruption)
        self.chbox_reboot.handler_block_by_func(self.cb_chbox_fixtext_reboot)
        if fixtext:

            self.box_detail.set_sensitive(True)

            if fixtext.fixref:
                self.entry_reference.set_text(fixtext.fixref)
            else:
                self.entry_reference.set_text("")
            
            self.chbox_reboot.set_active(fixtext.reboot)
            self.set_active_comboBox(self.combo_strategy, fixtext.strategy, self.COMBO_COLUMN_DATA, "fixtext strategy")
            self.set_active_comboBox(self.combo_complexity, fixtext.complexity, self.COMBO_COLUMN_DATA, "fixtext complexity")
            self.set_active_comboBox(self.combo_disruption, fixtext.disruption, self.COMBO_COLUMN_DATA, "fixtext disruption")
        else:
            self.item = None
            self.box_detail.set_sensitive(False)
            self.entry_reference.set_text("")
            self.chbox_reboot.set_active(False)
            self.combo_strategy.set_active(-1)
            self.combo_complexity.set_active(-1)
            self.combo_disruption.set_active(-1)
            
        self.combo_strategy.handler_unblock_by_func(self.cb_combo_fixtext_strategy)
        self.combo_complexity.handler_unblock_by_func(self.cb_combo_fixtext_complexity)
        self.combo_disruption.handler_unblock_by_func(self.cb_combo_fixtext_disruption)
        self.chbox_reboot.handler_unblock_by_func(self.cb_chbox_fixtext_reboot)
            
            

#======================================= EDIT FIX ==========================================

class EditFix(commands.DHEditItems, abstract.ControlEditWindow, EventObject):
    
    COLUMN_ID = 0
    COLUMN_TEXT = 1
    COLUMN_OBJECT = 2
    
    def __init__(self, core, builder):
        
        self.id = "gui:btn:menu:edit:fix"
        self.builder = builder
        self.core = core
        
        EventObject.__init__(self, core)
        self.core.register(self.id, self)
        self.add_sender(self.id, "item_changed")
        
        self.edit_fix_option = EditFixOption(core, builder)
        self.add_receiver("gui:btn:menu:edit:fix", "item_changed", self.__update)
        
        self.model = gtk.ListStore(str, str, gobject.TYPE_PYOBJECT)
        lv = self.builder.get_object("edit:operations:lv_fix")
        lv.set_model(self.model)
        
                #information for new/edit dialog
        values = {
                    "name_dialog":  "Fix",
                    "view":         lv,
                    "cb":           self.DHEditFix,
                    "textEntry":    {"name":    "ID",
                                    "column":   self.COLUMN_ID,
                                    "empty":    False, 
                                    "unique":   True},
                    "textView":     {"name":    "Content",
                                    "column":   self.COLUMN_TEXT,
                                    "empty":    False, 
                                    "unique":   False}
                        }
        abstract.ControlEditWindow.__init__(self, core, lv, values)
        btn_add = builder.get_object("edit:operations:btn_fix_add")
        btn_edit = builder.get_object("edit:operations:btn_fix_edit")
        btn_del = builder.get_object("edit:operations:btn_fix_del")
        
        # set callBack to btn
        btn_add.connect("clicked", self.cb_add_row)
        btn_edit.connect("clicked", self.cb_edit_row)
        btn_del.connect("clicked", self.cb_del_row)
        
        abstract.ControlEditWindow.__init__(self, core, lv, values)
        self.selection.connect("changed", self.__cb_item_changed, lv)
        
        self.box_main = self.builder.get_object("edit:operations:fix:box")
        
        self.addColumn("ID",self.COLUMN_ID)
        self.addColumn("Content",self.COLUMN_TEXT)
        
    def fill(self, item):
        self.model.clear()
        self.emit("item_changed")
        if item:
            self.item = item
            rule = item.to_rule()
            for object in rule.fixes:
                self.model.append([object.id, object.content, object])
        else:
            self.item = None
    
    def set_sensitive(self, sensitive):
        self.box_main.set_sensitive(sensitive)
        
    def __cb_item_changed(self, widget, treeView):
        self.emit("item_changed")
        treeView.columns_autosize()
    
    def __update(self):
        (model,iter) = self.selection.get_selected()
 
        if iter:
            self.edit_fix_option.fill(model.get_value(iter,self.COLUMN_OBJECT))
        else:
            self.edit_fix_option.fill(None)

            
class EditFixOption(commands.DHEditItems,abstract.ControlEditWindow):
    
    def __init__(self, core, builder):
    
        # set  models
        self.core = core
        self.builder = builder

        #edit data of fictext
        self.entry_system = self.builder.get_object("edit:operations:fix:entry_system")
        self.entry_system.connect("focus-out-event",self.cb_entry_fix_system)
        
        self.entry_platform = self.builder.get_object("edit:operations:fix:entry_platform")
        self.entry_platform.connect("focus-out-event",self.cb_entry_fix_platform)
        
        self.combo_strategy = self.builder.get_object("edit:operations:fix:combo_strategy")
        self.set_model_to_comboBox(self.combo_strategy,self.combo_model_strategy, self.COMBO_COLUMN_VIEW)
        self.combo_strategy.connect( "changed", self.cb_combo_fix_strategy)
        
        self.combo_complexity = self.builder.get_object("edit:operations:fix:combo_complexity")
        self.set_model_to_comboBox(self.combo_complexity, self.combo_model_level, self.COMBO_COLUMN_VIEW)
        self.combo_complexity.connect( "changed", self.cb_combo_fix_complexity)
    
        self.combo_disruption = self.builder.get_object("edit:operations:fix:combo_disruption")
        self.set_model_to_comboBox(self.combo_disruption, self.combo_model_level, self.COMBO_COLUMN_VIEW)
        self.combo_disruption.connect( "changed", self.cb_combo_fix_disruption)
    
        self.chbox_reboot = self.builder.get_object("edit:operations:fix:chbox_reboot")
        self.chbox_reboot.connect("toggled",self.cb_chbox_fix_reboot)

        self.box_detail= self.builder.get_object("edit:operations:fix:frame")
        
    def fill(self, fix):
        self.item = fix
        self.combo_strategy.handler_block_by_func(self.cb_combo_fix_strategy)
        self.combo_complexity.handler_block_by_func(self.cb_combo_fix_complexity)
        self.combo_disruption.handler_block_by_func(self.cb_combo_fix_disruption)
        self.chbox_reboot.handler_block_by_func(self.cb_chbox_fix_reboot)
        if fix:

            self.box_detail.set_sensitive(True)

            if fix.system:
                self.entry_system.set_text(fix.system)
            else:
                self.entry_system.set_text("")

            if fix.platform:
                self.entry_platform.set_text(fix.platform)
            else:
                self.entry_platform.set_text("")
                
            self.chbox_reboot.set_active(fix.reboot)
            self.set_active_comboBox(self.combo_strategy, fix.strategy, self.COMBO_COLUMN_DATA,  "fix strategy")
            self.set_active_comboBox(self.combo_complexity, fix.complexity, self.COMBO_COLUMN_DATA, "fix complexity")
            self.set_active_comboBox(self.combo_disruption, fix.disruption, self.COMBO_COLUMN_DATA, "fix disruption")
        else:
            self.item = None
            self.box_detail.set_sensitive(False)
            self.entry_system.set_text("")
            self.entry_platform.set_text("")
            self.chbox_reboot.set_active(False)
            self.combo_strategy.set_active(-1)
            self.combo_complexity.set_active(-1)
            self.combo_disruption.set_active(-1)
            
        self.combo_strategy.handler_unblock_by_func(self.cb_combo_fix_strategy)
        self.combo_complexity.handler_unblock_by_func(self.cb_combo_fix_complexity)
        self.combo_disruption.handler_unblock_by_func(self.cb_combo_fix_disruption)
        self.chbox_reboot.handler_unblock_by_func(self.cb_chbox_fix_reboot)

class EditAddProfileDialogWindow(EventObject, abstract.ControlEditWindow):

    def __init__(self, core, data_model, cb):
        self.core = core
        self.data_model = data_model
        self.__update = cb
        builder = gtk.Builder()
        builder.add_from_file("/usr/share/scap-workbench/edit_item.glade")
        self.window = builder.get_object("dialog:profile_add")

        builder.get_object("profile_add:btn_ok").connect("clicked", self.__cb_do)
        builder.get_object("profile_add:btn_cancel").connect("clicked", self.__delete_event)
        self.id = builder.get_object("profile_add:entry_id")
        self.title = builder.get_object("profile_add:entry_title")
        self.info_box = builder.get_object("profile_add:info_box")

        self.lang = builder.get_object("profile_add:entry_lang")
        self.lang.set_text(self.core.selected_lang or "")

        self.show()

    def __cb_do(self, widget):

        if len(self.id.get_text()) == 0: 
            self.core.notify("Can't add profile with no ID !", 2, self.info_box, msg_id="notify:edit:profile:new")
            return
        if len(self.title.get_text()) == 0: 
            self.core.notify("Please add title for this profile.", 2, self.info_box, msg_id="notify:edit:profile:new")
            self.title.grab_focus()
            #return

        values = {}
        values["id"] = self.id.get_text()
        values["abstract"] = False
        values["version"] = ""
        values["extends"] = None
        values["details"] = [{"lang": self.lang.get_text(), "title": self.title.get_text(), "description": None}]
        self.data_model.add(values)
        self.core.selected_profile = self.id.get_text()
        self.core.force_reload_profiles = True
        self.window.destroy()
        self.__update(new=True)

    def show(self):
        self.window.set_transient_for(self.core.main_window)
        self.window.show()

    def __delete_event(self, widget, event=None):
        self.window.destroy()
        

class AddItem(EventObject, abstract.ControlEditWindow):
    
    COMBO_COLUMN_DATA = 0
    COMBO_COLUMN_VIEW = 1
    COMBO_COLUMN_INFO = 2
    
    def __init__(self, core, data_model, list_item, ref_model):
        
        self.core = core
        self.data_model = data_model
        self.view = list_item.get_TreeView()
        self.ref_model = ref_model#list_item.get_TreeView().get_model()
        self.map_filterInfo = list_item.map_filter
        
        self.builder = gtk.Builder()
        self.builder.add_from_file("/usr/share/scap-workbench/edit_item.glade")
        self.window = self.builder.get_object("dialog:add_item")
        self.window.connect("delete-event", self.__delete_event)
        
        btn_ok = self.builder.get_object("dialog:add_item:btn_ok")
        btn_ok.connect("clicked", self.__cb_do)
        btn_cancel = self.builder.get_object("dialog:add_item:btn_cancel")
        btn_cancel.connect("clicked", self.__delete_event)

        self.itype = self.builder.get_object("dialog:add_item:type")
        self.itype.connect("changed", self.__cb_changed_type)
        self.vtype = self.builder.get_object("dialog:add_item:value_type")
        self.iid = self.builder.get_object("dialog:add_item:id")
        self.lang = self.builder.get_object("dialog:add_item:lang")
        self.lang.set_text(self.core.selected_lang)
        self.lang.set_sensitive(False)
        self.title = self.builder.get_object("dialog:add_item:title")
        self.relation = self.builder.get_object("dialog:add_item:relation")
        self.relation.connect("changed", self.__cb_changed_relation)
        self.info_box = self.builder.get_object("dialog:add_item:info_box")

        self.__entry_style = self.iid.get_style().base[gtk.STATE_NORMAL]

        #TODO: remove this section -> move it to commander
        self.selection = self.data_model.treeView.get_selection()
        if self.selection != None:
            (self.model, self.iter) = self.selection.get_selected()
            if self.iter == None: return False
            self.parent = self.data_model.get_item(self.model[self.iter][self.data_model.COLUMN_ID])
            
        self.show()

    def __cb_changed_relation(self, widget):

        self.core.notify_destroy("dialog:add_item")
        if self.model[self.iter][self.data_model.COLUMN_TYPE] == "value" and widget.get_active() == self.data_model.RELATION_CHILD:
            self.core.notify("Item type VALUE can't be a parent !", 2, self.info_box, msg_id="dialog:add_item")
            self.itype.grab_focus()
            return

    def __cb_changed_type(self, widget):

        self.core.notify_destroy("dialog:add_item")
        if widget.get_active() == self.data_model.TYPE_VALUE:
            self.builder.get_object("dialog:add_item:value_type:lbl").set_visible(True)
            self.vtype.set_visible(True)
        else: 
            self.builder.get_object("dialog:add_item:value_type:lbl").set_visible(False)
            self.vtype.set_visible(False)

    def __cb_do(self, widget):

        self.core.notify_destroy("dialog:add_item")
        tagOK = True
        itype = self.itype.get_active()
        vtype = self.vtype.get_active()
        relation = self.relation.get_active()
        if itype == -1:
            self.core.notify("Relation has to be chosen", 2, self.info_box, msg_id="dialog:add_item")
            self.itype.grab_focus()
            return

        if itype == self.data_model.TYPE_VALUE:
            if vtype == -1:
                self.core.notify("Type of value has to be choosen", 2, self.info_box, msg_id="dialog:add_item")
                self.vtype.grab_focus()
                return

        if relation == -1:
            self.core.notify("Relation has to be chosen", 2, self.info_box, msg_id="dialog:add_item")
            self.relation.grab_focus()
            return
        elif relation == self.data_model.RELATION_CHILD and parent.type == self.data_model.TYPE_VALUE:
            self.core.notify("Type of value has ", 2, self.info_box, msg_id="dialog:add_item")
            self.vtype.grab_focus()
            return

        if self.iid.get_text() == "":
            self.core.notify("The ID of item is mandatory !", 2, self.info_box, msg_id="dialog:add_item")
            self.iid.grab_focus()
            self.iid.modify_base(gtk.STATE_NORMAL, gtk.gdk.Color("#FFC1C2"))
            return
        else: 
            self.iid.modify_base(gtk.STATE_NORMAL, self.__entry_style)

        if self.title.get_text() == "":
            self.core.notify("The title of item is mandatory !", 2, self.info_box, msg_id="dialog:add_item")
            self.title.grab_focus()
            self.title.modify_base(gtk.STATE_NORMAL, gtk.gdk.Color("#FFC1C2"))
            return
        else: 
            self.title.modify_base(gtk.STATE_NORMAL, self.__entry_style)

        if relation == self.data_model.RELATION_PARENT:
            self.core.notify("Relation PARENT is not implemented yet", 2, self.info_box, msg_id="dialog:add_item")
            self.relation.grab_focus()
            return

        item = {"id": self.iid.get_text(),
                "lang": self.lang.get_text(),
                "title": self.title.get_text()}
        retval = self.data_model.add_item(item, itype, relation, vtype)

        self.window.destroy()
            
    def show(self):
        self.window.set_transient_for(self.core.main_window)
        self.window.show()

    def __delete_event(self, widget, event=None):
        self.core.notify_destroy("dialog:add_item")
        self.window.destroy()

class EditSelectIdDialogWindow():
    
    COLUMN_ID = 0
    COLUMN_TITLE = 1
    COLUMN_SELECTED = 2
    
    def __init__(self, item, core, model_conflict, model_item, cb):
        self.core = core
        self.item = item
        self.cb = cb
        self.model_conflict = model_conflict
        self.model_item = model_item
        
        builder = gtk.Builder()
        builder.add_from_file("/usr/share/scap-workbench/edit_item.glade")

        self.window = builder.get_object("dialog:add_id")
        self.window.connect("delete-event", self.__delete_event)
        self.window.resize(800, 600)
        
        btn_ok = builder.get_object("add_id:btn_ok")
        btn_ok.connect("clicked", self.__cb_do)
        btn_cancel = builder.get_object("add_id:btn_cancel")
        btn_cancel.connect("clicked", self.__delete_event)

        btn_add = builder.get_object("add_id:btn_add")
        btn_add.connect("clicked", self.cb_btn_add)
        btn_remove = builder.get_object("add_id:btn_remove")
        btn_remove.connect("clicked", self.__cb_del_row)
        
        self.btn_search = builder.get_object("add_id:btn_search")
        self.btn_search.connect("clicked",self.__cb_search)
        self.btn_search_reset = builder.get_object("add_id:btn_search_reset")
        self.btn_search_reset.connect("clicked",self.__cb_search_reset)
        
        self.text_search_id = builder.get_object("add_id:text_search_id")
        self.text_search_title = builder.get_object("add_id:text_search_title")
        
        #treeView for search item for select to add
        self.model_search = gtk.TreeStore(str, str, bool)
        self.tw_search = builder.get_object("add_id:tw_search")
        
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn("ID Item", cell, text=self.COLUMN_ID)
        column.set_resizable(True)
        self.tw_search.append_column(column)

        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn("Title", cell, text=self.COLUMN_TITLE)
        column.set_expand(True)
        column.set_resizable(True)
        self.tw_search.append_column(column)
        
        self.tw_search.set_model(self.model_search)
        
        #treeView for item, which will be add
        self.model_to_add = gtk.ListStore(str, str)
        self.tw_add = builder.get_object("add_id:tw_add")
        
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn("ID Item", cell, text=self.COLUMN_ID)
        column.set_resizable(True)
        self.tw_add.append_column(column)

        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn("Title", cell, text=self.COLUMN_TITLE)
        column.set_expand(True)
        column.set_resizable(True)
        self.tw_add.append_column(column)

        self.tw_add.set_model(self.model_to_add)
        
        menu = gtk.Menu()
        menu_item = gtk.MenuItem("Remove from add")
        menu_item.show()
        menu.append(menu_item)
        menu_item.connect("activate", self.__cb_del_row)
        self.tw_add.connect ("button_press_event",self.cb_popupMenu_to_add, menu)
        self.tw_add.connect("key-press-event", self.__cb_del_row1,)

        menu_search = gtk.Menu()
        menu_item = gtk.MenuItem("Copy to add")
        menu_item.show()
        menu_search.append(menu_item)
        menu_item.connect("activate", self.cb_btn_add)
        self.tw_search.connect ("button_press_event",self.cb_popupMenu_to_add, menu_search)

        
        self.model_search.clear()
        self.copy_model(model_item, model_item.get_iter_first(), self.model_search, None)
        self.show()

    def __cb_do(self, widget):
        
        iter_add =  self.model_to_add.get_iter_first()
        while iter_add:
            #add row, which not added before
            exist = False
            iter = self.model_conflict.get_iter_first()
            id_add = self.model_to_add.get_value(iter_add,self.COLUMN_ID)
            while iter:
                if id_add == self.model_conflict.get_value(iter,self.COLUMN_ID):
                    exist = True
                iter = self.model_conflict.iter_next(iter)
            if not exist:
                self.cb(self.item, id_add, True)
                self.model_conflict.append([id_add])
            iter_add = self.model_to_add.iter_next(iter_add)
        self.window.destroy()
            
    def __cb_del_row1(self, widget, event):
        keyname = gtk.gdk.keyval_name(event.keyval)
        if keyname == "Delete":
            selection = self.tw_add.get_selection( )
            if selection != None: 
                (model, iter) = selection.get_selected( )
                if  iter != None:
                    model.remove(iter)

                        
    def __cb_del_row(self, widget):
        selection = self.tw_add.get_selection()
        (model, iter) = selection.get_selected()
        if iter != None:
            model.remove(iter)
    
    def cb_popupMenu_to_add (self, treeview, event, menu):
        if event.button == 3:
            time = event.time
            menu.popup(None,None,None,event.button,event.time)
            
    def show(self):
        self.window.set_transient_for(self.core.main_window)
        self.window.show()

    def __delete_event(self, widget, event=None):
        self.window.destroy()
            
    def __cb_toggled(self, cell, path ):
        
        self.model_search[path][self.COLUMN_SELECTED] = not self.model_search[path][self.COLUMN_SELECTED]
        id_item = self.model_search[path][self.COLUMN_ID]
        if not self.model_search[path][self.COLUMN_SELECTED]:
            # remve from model to add
            iter = self.model_to_add.get_iter_first()
            while iter:
                if self.model_to_add.get_value(iter,self.COLUMN_ID) == id_item:
                    self.model_to_add.remove(iter)
                    break
                iter = self.model_to_add.iter_next(iter)
        else:
            # move from serch model to model for add, if not there
            iter = self.model_to_add.get_iter_first()
            while iter:
                if self.model_to_add.get_value(iter,self.COLUMN_ID) == id_item:
                    return
                iter = self.model_to_add.iter_next(iter)
            self.model_to_add.append([id_item,self.model_search[path][self.COLUMN_TITLE]])
        # change state check box

    def cb_btn_add(self, widget):
        selection = self.tw_search.get_selection( )
        if selection != None: 
            (model, iter_add) = selection.get_selected( )
            if  iter_add != None:
                id_item = self.model_search.get_value(iter_add, self.COLUMN_ID)
                iter = self.model_to_add.get_iter_first()
                while iter:
                    if self.model_to_add.get_value(iter,self.COLUMN_ID) == id_item:
                        return
                    iter = self.model_to_add.iter_next(iter)
                self.model_to_add.append([id_item,self.model_search.get_value(iter_add, self.COLUMN_TITLE)])
            
    def copy_model(self, model_item, iter, model_search, iter_parent):
        """
        copy_model to search model
        """
        while iter:
            row = []
            row.append(model_item.get_value(iter,0))
            row.append(model_item.get_value(iter,3))
            row.append(False)
            iter_self = model_search.append(iter_parent, row)
            self.copy_model(model_item, model_item.iter_children(iter), model_search, iter_self)
            iter = model_item.iter_next(iter)
        return
    
    def __cb_search(self, widget):
        self.model_search.clear()
        self.search(self.model_item, self.model_item.get_iter_first(), self.model_search, 
                                self.text_search_id.get_text(), self.text_search_title.get_text())

    def __cb_search_reset(self, widget):
        self.model_search.clear()
        self.copy_model(self.model_item, self.model_item.get_iter_first(), self.model_search, None)
                                
    def search(self, model_item, iter, model_search, id, title):
        """ 
        Filter data to list
        """
        while iter:
            if self.match_fiter(id, title,  model_item, iter):
                row = []
                row.append(model_item.get_value(iter,0))
                row.append(model_item.get_value(iter,3))
                row.append(False)
                iter_to = model_search.append(None, row)
            self.search(model_item, model_item.iter_children(iter), model_search, id, title)
            iter = model_item.iter_next(iter)
    
    
    def match_fiter(self, id, title,  model_item, iter):
        try:
            pattern = re.compile(id,re.IGNORECASE)
            res_id = pattern.search(model_item.get_value(iter,0)) 
            pattern = re.compile(title,re.IGNORECASE)
            res_title = pattern.search(model_item.get_value(iter,3)) 
            
            if res_id == None or res_title == None:
                return False
            return True
        except Exception, e:
            #self.core.notify("Can't filter items: %s" % (e,), 3)
            logger.error("Can't filter items: %s" % (e,))
            return False
    


class EditValueChoice(commands.DataHandler, abstract.EnterList):
    
    COLUMN_MARK_ROW = 0
    COLUMN_CHOICE = 1

    def __init__(self, core, model, treeView, window):

        self.model = model
        self.treeView = treeView
        abstract.EnterList.__init__(self, core, "EditValueCoice",self.model, self.treeView, self.cb_lv_edit , window)
        
        cell = self.set_insertColumnText("Choice", self.COLUMN_CHOICE, True, True)
        iter = self.model.append(None)
        self.model.set(iter,self.COLUMN_MARK_ROW,"*")

    def cb_lv_edit(self, action):
    
        if action == "edit":
            self.model[self.edit_path][self.edit_column] = self.edit_text
        elif action == "del":
            self.model.remove(self.iter_del)
        elif action == "add":
            self.model[self.edit_path][self.edit_column] = self.edit_text
