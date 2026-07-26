"""
PathValidationController - Handles validation and recovery of missing image and mask paths.

This controller manages the UI orchestration for validating that image and mask files exist,
and prompts users to locate missing files when paths are invalid.
"""

import os
from pathlib import Path
from PySide6.QtWidgets import QMessageBox, QFileDialog
from core.services.LoggerService import LoggerService
from helpers.TranslationMixin import TranslationMixin
from helpers.PathHelper import (
    cross_platform_basename,
    index_folder_by_filename,
    find_in_index,
)


class PathValidationController(TranslationMixin):
    """
    Controller for managing path validation and recovery.

    Handles checking for missing files and prompting users to locate them.
    """

    def __init__(self, parent_viewer):
        """
        Initialize the path validation controller.

        Args:
            parent_viewer: The main Viewer instance
        """
        self.parent = parent_viewer
        self.logger = LoggerService()
        # Set by _ask_retry_or_continue: whether the user chose to load with a
        # partial recovery rather than cancel.
        self._continued = False

    def validate_and_fix_paths(self, images):
        """
        Validate that all image and mask paths exist. Prompt user to select folders if missing.

        Args:
            images: List of image dictionaries to validate

        Returns:
            bool: True if all paths are valid or were fixed, False if user cancelled.
        """
        missing_images = []
        missing_masks = []

        # Check which images and masks are missing
        for image in images:
            image_path = image.get('path', '')
            mask_path = image.get('mask_path', '')

            # cross_platform_basename, not os.path.basename: a result file
            # authored on Windows stores "C:\Flight1\DJI_0042.JPG", and on
            # POSIX os.path.basename returns that whole string as the
            # "filename". Joining it onto the folder the user picks can never
            # match, so recovery reported every image as still missing no
            # matter how correct the chosen folder was.
            if image_path and not os.path.exists(image_path):
                missing_images.append({
                    'image': image,
                    'filename': cross_platform_basename(image_path)
                })

            if mask_path and not os.path.exists(mask_path):
                missing_masks.append({
                    'image': image,
                    'filename': cross_platform_basename(mask_path)
                })

        # Prompt for source images folder if any are missing
        if missing_images:
            if not self._prompt_for_source_folder(missing_images):
                return False  # User cancelled

        # Prompt for masks folder if any are missing
        if missing_masks:
            if not self._prompt_for_mask_folder(missing_masks):
                return False  # User cancelled

        return True

    def _prompt_for_source_folder(self, missing_images):
        """
        Prompt user to select folder containing source images.

        Args:
            missing_images (list): List of dicts with 'image' and 'filename' keys.

        Returns:
            bool: True if successful, False if user cancelled.
        """
        return self._recover_missing_files(
            missing_images,
            path_key='path',
            labels={
                'not_found_title': self.tr("Source Images Not Found"),
                'not_found_message': self.tr(
                    "{count} source image(s) not found at expected locations:\n\n"
                    "{files}\n\n"
                    "Please select the folder containing the source images."
                ),
                'picker_title': self.tr("Select Source Images Folder"),
                'partial_title': self.tr("Some Images Still Missing"),
                'partial_message': self.tr(
                    "Found {found} of {total} images.\n\n"
                    "Still missing:\n{missing}"
                ),
                'none_message': self.tr(
                    "None of the {total} missing images were found in that folder "
                    "(including its subfolders).\n\n"
                    "Expected to find files named:\n{missing}"
                ),
            },
        )

    def _prompt_for_mask_folder(self, missing_masks):
        """
        Prompt user to select folder containing detection masks.

        Args:
            missing_masks (list): List of dicts with 'image' and 'filename' keys.

        Returns:
            bool: True if successful, False if user cancelled.
        """
        return self._recover_missing_files(
            missing_masks,
            path_key='mask_path',
            labels={
                'not_found_title': self.tr("Detection Masks Not Found"),
                'not_found_message': self.tr(
                    "{count} detection mask(s) not found at expected locations:\n\n"
                    "{files}\n\n"
                    "Please select the folder containing the mask files."
                ),
                'picker_title': self.tr("Select Masks Folder"),
                'partial_title': self.tr("Some Masks Still Missing"),
                'partial_message': self.tr(
                    "Found {found} of {total} masks.\n\n"
                    "Still missing:\n{missing}"
                ),
                'none_message': self.tr(
                    "None of the {total} missing masks were found in that folder "
                    "(including its subfolders).\n\n"
                    "Expected to find files named:\n{missing}"
                ),
            },
        )

    def _recover_missing_files(self, missing, path_key, labels):
        """Prompt for a replacement folder and relocate *missing* files in it.

        Shared by the image and mask recovery paths: the only differences are
        the dictionary key being repaired and the wording.

        Matching is done against a single recursive index of the chosen folder
        (see :func:`helpers.PathHelper.index_folder_by_filename`) rather than
        one ``os.path.exists`` per candidate. That fixes three separate reasons
        a correct folder used to be rejected:

        * filenames derived from Windows-authored paths (handled upstream by
          ``cross_platform_basename``),
        * drone media nested in subfolders (``DCIM/100MEDIA/...``) - the old
          flat join only ever looked directly inside the chosen folder,
        * case and Unicode-normalization drift between the machine that wrote
          the result file and the one reviewing it.

        A partial match no longer hard-fails the whole load either: the user can
        pick a different folder or continue with what was found.

        Args:
            missing (list): Dicts with 'image' and 'filename' keys.
            path_key (str): Key on the image dict to repair ('path'/'mask_path').
            labels (dict): Pre-translated user-facing strings.

        Returns:
            bool: True to continue loading, False if the user cancelled.
        """
        if not self._confirm_recovery(missing, labels):
            return False

        start_dir = ""
        while True:
            folder = QFileDialog.getExistingDirectory(
                self.parent,
                labels['picker_title'],
                start_dir,
                QFileDialog.ShowDirsOnly
            )
            if not folder:
                return False  # User cancelled

            # Re-open the picker where they last looked, not at the root.
            start_dir = folder

            index = index_folder_by_filename(folder)
            resolved = {}
            still_missing = []
            for item in missing:
                located = find_in_index(item['filename'], index)
                if located:
                    resolved[id(item)] = located
                else:
                    still_missing.append(item['filename'])

            if not still_missing:
                self._apply_resolved(missing, resolved, path_key, folder)
                self.logger.info(
                    f"Relocated {len(resolved)} {path_key} entries to {folder}"
                )
                return True

            # Apply whatever was found before asking, so "Continue Anyway"
            # keeps the partial recovery instead of discarding it.
            self._apply_resolved(missing, resolved, path_key, folder)
            self.logger.warning(
                f"Relocated {len(resolved)} of {len(missing)} {path_key} entries "
                f"in {folder}; {len(still_missing)} unresolved"
            )

            if not self._ask_retry_or_continue(
                missing, still_missing, len(resolved), labels
            ):
                return self._continued

    def _confirm_recovery(self, missing, labels):
        """Tell the user what is missing and confirm they want to go looking."""
        file_list = self._format_file_list([item['filename'] for item in missing])
        msg_box = QMessageBox(self.parent)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setWindowTitle(labels['not_found_title'])
        msg_box.setText(
            labels['not_found_message'].format(count=len(missing), files=file_list)
        )
        msg_box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg_box.setDefaultButton(QMessageBox.Ok)
        return msg_box.exec() == QMessageBox.Ok

    def _ask_retry_or_continue(self, missing, still_missing, found_count, labels):
        """Offer another folder, continuing partially, or cancelling.

        Returns:
            bool: True to loop and pick another folder. False to stop, with
            ``self._continued`` recording whether the user chose to continue
            with a partial recovery (True) or to cancel the load (False).
        """
        missing_list = self._format_file_list(still_missing)
        template = labels['partial_message'] if found_count else labels['none_message']
        text = template.format(
            found=found_count, total=len(missing), missing=missing_list
        )

        msg_box = QMessageBox(self.parent)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle(labels['partial_title'])
        msg_box.setText(text)
        retry_button = msg_box.addButton(
            self.tr("Choose Another Folder"), QMessageBox.AcceptRole
        )
        continue_button = None
        if found_count:
            # Losing a whole review because one capture of several hundred was
            # deleted is worse than reviewing the ones that are present.
            continue_button = msg_box.addButton(
                self.tr("Continue Anyway"), QMessageBox.DestructiveRole
            )
        msg_box.addButton(QMessageBox.Cancel)
        msg_box.setDefaultButton(retry_button)
        msg_box.exec()

        clicked = msg_box.clickedButton()
        if clicked is retry_button:
            self._continued = False
            return True
        # Guard against clickedButton() being None (dialog dismissed with Esc):
        # `clicked is continue_button` would be True when both are None, which
        # would silently continue a load the user tried to cancel.
        self._continued = continue_button is not None and clicked is continue_button
        return False

    def _apply_resolved(self, missing, resolved, path_key, folder):
        """Write located paths onto the image dicts and persist them.

        Persisting matters as much as the in-memory fix: without it every
        subsequent open of the same result file re-prompts for the same folder.
        Both are best-effort - a result file on read-only media or a shared
        drive must not fail the load.

        Args:
            missing (list): The dicts passed to :meth:`_recover_missing_files`.
            resolved (dict): id(item) -> located path.
            path_key (str): Key to repair ('path' or 'mask_path').
            folder (str): The folder the user chose.
        """
        if not resolved:
            return

        for item in missing:
            located = resolved.get(id(item))
            if not located:
                continue
            item['image'][path_key] = located
            # get_images() resolves a stored absolute path as-is (and
            # os.path.join returns an absolute second argument unchanged, so an
            # absolute mask_path also survives the xml_dir join), which keeps
            # the written value readable by older builds.
            image_xml = item['image'].get('xml')
            if image_xml is not None:
                try:
                    image_xml.set(path_key, located)
                except Exception as e:
                    self.logger.warning(
                        f"Could not update {path_key} in result XML for "
                        f"{item['filename']}: {e}"
                    )

        if path_key == 'path':
            self._update_input_dir(folder)
        self._save_result_file()

    def _update_input_dir(self, folder):
        """Point settings['input_dir'] at the recovered folder.

        Viewer._build_source_images() enumerates the full flight from
        settings['input_dir']. Leaving it at the original capture folder means
        the map, coverage extents and WALDO heading derivation all silently
        fall back to the AOI subset even though the images were just located.
        """
        settings = getattr(self.parent, 'settings', None)
        if isinstance(settings, dict):
            settings['input_dir'] = folder

    def _save_result_file(self):
        """Persist repaired paths to the result XML (best effort)."""
        xml_service = getattr(self.parent, 'xml_service', None)
        xml_path = getattr(self.parent, 'xml_path', None)
        if xml_service is None or not xml_path:
            return
        try:
            xml_service.save_xml_file(xml_path)
        except Exception as e:
            # Read-only media or a locked file: the in-memory repair still
            # stands for this session, so the load continues.
            self.logger.warning(
                f"Could not persist relocated paths to {xml_path}: {e}"
            )

    def _format_file_list(self, filenames, limit=10):
        """Render a bulleted, truncated filename list for a message box."""
        listing = '\n'.join([f"  • {name}" for name in filenames[:limit]])
        if len(filenames) > limit:
            listing += self.tr("\n  ... and {count} more").format(
                count=len(filenames) - limit
            )
        return listing
