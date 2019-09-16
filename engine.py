"""
A SilhouetteFX engine for Tank.

"""

import sgtk
import copy
import os
import logging
import shutil

from sgtk.platform import Engine
from sgtk import TankError

class SilhouetteEngine(Engine):
    @property
    def context_change_allowed(self):
        return True

    @property
    def host_info(self):
        host_info = {"name": "Silhouette", "version": "unknown"}
        try:
            import fx
            host_info['version'] = str(fx.version)
        except:
            # Fallback to initialized above
            pass

        return host_info

    def create_shotgun_menu(self):
        if self.has_ui:
            # get all environments
            pc = self.sgtk.pipeline_configuration
            env_names_to_process = pc.get_environments()
            # current env app commands will already be available in engine.commands
            env_names_to_process.remove(self.env.name)
            commands_to_write = {}

            # collect commands registered by apps from all environments
            for env_name in env_names_to_process:
                env_obj = pc.get_environment(env_name, writable=True)

                if self.name in env_obj.get_engines():
                    # reusing generous chunks of engine.__load_apps()
                    app_names_to_process = env_obj.get_apps(self.instance_name)
                    for app_instance_name in app_names_to_process:
                        app_descriptor = env_obj.get_app_descriptor(self.instance_name, app_instance_name)
                        app_path = app_descriptor.get_path()

                        # we have already initialised some apps
                        if not app_instance_name in self.apps:
                            old_command_keys = copy.deepcopy(self.commands.keys())
                            try:
                                app_obj = sgtk.platform.engine.load_application(self, self.context,
                                                                                env_obj, app_instance_name)

                            except TankError as e:
                                # validation error - probably some issue with the settings!
                                # report this as an error message.
                                self.log_error(
                                    "App configuration Error for %s (configured in environment '%s'). "
                                    "It will not be loaded: %s" % (
                                    app_instance_name, env_obj.disk_location, e))
                                continue

                            except Exception:
                                # code execution error in the validation. Report this as an error
                                # with the engire call stack!
                                self.log_exception("A general exception was caught while trying to "
                                                   "load the application %s located at '%s'. "
                                                   "The app will not be loaded." % (
                                                   app_instance_name, env_obj.disk_location))
                                continue

                                # initialize the app

                            try:
                                # track the init of the app
                                self.__currently_initializing_app = app_obj
                                try:
                                    app_obj.init_app()
                                finally:
                                    self.__currently_initializing_app = None

                            except TankError as e:
                                self.log_error(
                                    "App %s failed to initialize. It will not be loaded: %s" % (
                                    app_path, e))

                            except Exception:
                                self.log_exception(
                                    "App %s failed to initialize. It will not be loaded." % app_path)

                            finally:
                                # clean up commands and add the new commands to silhouette actions
                                # TODO: is this all?
                                new_command_names = set(self.commands.keys()) - set(old_command_keys)
                                for new_command_name in new_command_names:
                                    commands_to_write[new_command_name] = self.commands[new_command_name]
                                    self.commands.pop(new_command_name)
                                app_obj.destroy_app()

            commands_to_write.update(self.commands)

            # Get temp folder path and create it if needed.
            self.custom_scripts_dir_path = os.environ['TK_SILHOUETTE_MENU_DIR']
            sgtk.util.filesystem.ensure_folder_exists(self.custom_scripts_dir_path)

            # Clear it.
            for item in os.listdir(self.custom_scripts_dir_path):
                os.remove(os.path.join(self.custom_scripts_dir_path, item))

            # Write a file for each action
            for i, (command_name, command) in enumerate(commands_to_write.iteritems()):
                action_class_name = command["properties"].get("short_name") or \
                                    "tk_silhouette_cmd_{}".format(i)
                self.__write_silhouette_action(command_name, action_class_name)
                self.logger.debug("Action written for {} {}".format(command_name, command))

            return True
        else:
            return False

    def add_silhouette_hooks(self):
        import hook
        hook.add("quit", self.destroy_engine)

    def post_app_init(self):
        self.create_shotgun_menu()
        self.add_silhouette_hooks()

    def post_qt_init(self):
        self._initialize_dark_look_and_feel()

    def post_context_change(self, old_context, new_context):
        self.create_shotgun_menu()

    def destroy_engine(self):
        self.logger.debug("%s: Destroying...", self)

        try:
            shutil.rmtree(self.custom_scripts_dir_path)
        except OSError as error:
            if error.errno != 2: # Don't error if folder not found.
                raise

    @property
    def has_ui(self):
        return True

    ##########################################################################################
    # logging

    def _emit_log_message(self, handler, record):
        if record.levelno < logging.INFO:
            formatter = logging.Formatter("Debug: Shotgun %(basename)s: %(message)s")
        else:
            formatter = logging.Formatter("Shotgun %(basename)s: %(message)s")

        msg = formatter.format(record)

        print msg

    # def _create_dialog(self, title, bundle, widget, parent):
    #     from sgtk.platform.qt import QtCore
    #     dialog = super(SilhouetteEngine, self)._create_dialog(title, bundle, widget, parent)
    #     dialog.setWindowFlags(dialog.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
    #     dialog.setWindowState(
    #         (dialog.windowState() & ~QtCore.Qt.WindowMinimized) | QtCore.Qt.WindowActive)
    #     dialog.raise_()
    #     dialog.activateWindow()
    #     return dialog

    ##########################################################################################
    def __write_silhouette_action(self, command_name, action_class):
        """
        Write a silhouette action which will be enabled
        if the given command is part of the current engine's commands attribute
        and will call the command callback in the execute method

        :param command_name:
        :param command:

        """
        script_path = os.path.join(self.custom_scripts_dir_path, "{}.py".format(action_class))
        f = open(script_path, "w")
        f.write("\n".join([
            "import sgtk",
            "from fx import Action, addAction",
            "class {short_name}(Action):".format(short_name=action_class),
            "   def __init__(self):",
            "       self.sgtk_engine_command_name = '{display_name}'".format(display_name=command_name),
            "       Action.__init__(self, self.sgtk_engine_command_name, root='Shotgun')",
            "   def available(self):",
            "       current_engine = sgtk.platform.current_engine()",
            "       assert self.sgtk_engine_command_name in current_engine.commands, 'Command not available in current environment'",
            "   def execute(self):",
            "       current_engine = sgtk.platform.current_engine()",
            "       current_engine.commands[self.sgtk_engine_command_name]['callback']()",
            "addAction({short_name}())".format(short_name=action_class),
        ]))
        f.close()
