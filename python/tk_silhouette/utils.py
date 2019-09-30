import os
import re
import fx

import sgtk

# sources have path format /path/to/file.[start-end].ext
SILHOUETTE_FRAME_REGEX = "\.\[(\d+)-\d+\]\."

def seq_path_to_silhouette_format(tk, path):
    """
    Replace the SEQ key in the path with frame range in
    "[<start>-<end>]" format expected by silhouette

    :param tk:          Tank object
    :param path:        Path to format containing SEQ keys
    :return:            Path in format /path/to/file.[start-end].ext
    """
    #
    error_message = None
    formatted_path = path

    path_template = tk.template_from_path(path)
    if path_template:
        path_fields = path_template.get_fields(path)

        if "SEQ" in path_fields:
            # If we have something to replace, get the frame range string ready
            start_frame, end_frame = find_sequence_range(tk, path)
            frame_range_string = "[{}-{}]".format(start_frame, end_frame)

            # TODO: More secure to create a temporary template with all SEQ keys
            # replaced with a string key and apply this as value,
            # to avoid replacing some other key that contains
            # the default SEQ expression within it
            replace_value = path_fields["SEQ"]
            formatted_path = formatted_path.replace(replace_value, frame_range_string)
        else:
            error_message = "Path {} fits template {} which has no key called SEQ. " \
                              "Not formatting it with frame range.".format(path, path_template)
    else:
        error_message = "Path {} does not fit any template. " \
                          "Not formatting it with frame range.".format(path)

    return formatted_path, error_message

def seq_path_from_silhouette_format(tk, path):
    """
    Replace the path with frame range in "[<start>-<end>]" format
    obtained from silhouette with defaults for any SequenceKey

    :param tk:          Tank object
    :param path:        Path obtained from silhouette with "[<start>-<end>]"
                        frame range format
    :return:            Path with sgtk default SequenceKey formatting
    """
    error_message = None

    compiled_regex = re.compile(SILHOUETTE_FRAME_REGEX)
    match = compiled_regex.search(path)
    if not match:
        error_message = "No [start-end] found in source path `{}`. " \
                        "Not formatting dependency path.".format(path)
        return path, error_message

    first_frame = int(match.group(1))
    first_frame_path = compiled_regex.sub(".\\g<1>.", path)

    # retrieve the template and remove the seq key to replace it with the default
    path_template = tk.template_from_path(first_frame_path)
    if not path_template:
        error_message = "No template found to match path `{}`. " \
                        "Not formatting dependency path.".format(path)
        return path, error_message

    fields = path_template.get_fields(first_frame_path)
    for key, value in fields.items():
        if value == first_frame:
            del fields[key]

    seq_format_path = path_template.apply_fields(fields)
    return seq_format_path, error_message


def get_stripped_project_path(project_path):
    """
    Convert /path/to/projects/<project_name>.sfx/project.sfx
    to /path/to/projects/<project_name> expected by silhouette functions

    :param project_path: Path to project.sfx file
    :return:             Path to project dir without .sfx suffix
    """
    processed_path = os.path.dirname(project_path)
    if processed_path.endswith(".sfx"):
        processed_path = processed_path[:-4]
    return processed_path


def warn_with_pop_up(logger, title, message):
    logger.warning(message)
    fx.displayWarning(message, title)


###########################################################################################
# copied from tk_multi_loader.utils
# TODO: put in a more generic location?

def sequence_range_from_path(path):
    """
    Parses the file name in an attempt to determine the first and last
    frame number of a sequence. This assumes some sort of common convention
    for the file names, where the frame number is an integer at the end of
    the basename, just ahead of the file extension, such as
    file.0001.jpg, or file_001.jpg. We also check for input file names with
    abstracted frame number tokens, such as file.####.jpg, or file.%04d.jpg.

    :param str path: The file path to parse.

    :returns: None if no range could be determined, otherwise (min, max)
    :rtype: tuple or None
    """
    # This pattern will match the following at the end of a string and
    # retain the frame number or frame token as group(1) in the resulting
    # match object:
    #
    # 0001
    # ####
    # %04d
    #
    # The number of digits or hashes does not matter; we match as many as
    # exist.
    frame_pattern = re.compile(r"([0-9#]+|[%]0\dd)$")
    root, ext = os.path.splitext(path)
    match = re.search(frame_pattern, root)

    # If we did not match, we don't know how to parse the file name, or there
    # is no frame number to extract.
    if not match:
        return None

    # We need to get all files that match the pattern from disk so that we
    # can determine what the min and max frame number is.
    glob_path = "%s%s" % (
        re.sub(frame_pattern, "*", root),
        ext,
    )
    files = glob.glob(glob_path)

    # Our pattern from above matches against the file root, so we need
    # to chop off the extension at the end.
    file_roots = [os.path.splitext(f)[0] for f in files]

    # We know that the search will result in a match at this point, otherwise
    # the glob wouldn't have found the file. We can search and pull group 1
    # to get the integer frame number from the file root name.
    frames = [int(re.search(frame_pattern, f).group(1)) for f in file_roots]
    return min(frames), max(frames)


def find_sequence_range(tk, path):
    """
    Helper method attempting to extract sequence information.

    Using the toolkit template system, the path will be probed to
    check if it is a sequence, and if so, frame information is
    attempted to be extracted.

    :param path: Path to file on disk.
    :returns: None if no range could be determined, otherwise (min, max)
    """
    # find a template that matches the path:
    template = None
    try:
        template = tk.template_from_path(path)
    except TankError:
        pass

    if not template:
        # If we don't have a template to take advantage of, then
        # we are forced to do some rough parsing ourselves to try
        # to determine the frame range.
        return sequence_range_from_path(path)

    # get the fields and find all matching files:
    fields = template.get_fields(path)
    if "SEQ" not in fields:
        # Ticket #655: older paths match wrong templates,
        # so fall back on path parsing
        return sequence_range_from_path(path)

    files = tk.paths_from_template(template, fields, ["SEQ", "eye"])

    # find frame numbers from these files:
    frames = []
    for file in files:
        fields = template.get_fields(file)
        frame = fields.get("SEQ")
        if frame != None:
            frames.append(frame)
    if not frames:
        return None

    # return the range
    return min(frames), max(frames)
