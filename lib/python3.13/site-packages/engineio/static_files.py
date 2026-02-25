content_types = {
    'css': 'text/css',
    'gif': 'image/gif',
    'html': 'text/html',
    'jpg': 'image/jpeg',
    'js': 'application/javascript',
    'json': 'application/json',
    'png': 'image/png',
    'txt': 'text/plain',
}


def get_static_file(path, static_files):
    """Return the local filename and content type for the requested static
    file URL.

    :param path: the path portion of the requested URL.
    :param static_files: a static file configuration dictionary.

    This function returns a dictionary with two keys, "filename" and
    "content_type". If the requested URL does not match any static file, the
    return value is None.
    """
    extra_path = ''
    if path in static_files:
        f = static_files[path]
    else:
        f = None
        while path != '':
            path, last = path.rsplit('/', 1)
            extra_path = '/' + last + extra_path
            if path in static_files:
                f = static_files[path]
                break
            elif path + '/' in static_files:
                f = static_files[path + '/']
                break
    if f:
        if isinstance(f, str):
            f = {'filename': f}
        else:
            f = f.copy()  # in case it is mutated below
        if f['filename'].endswith('/') and extra_path.startswith('/'):
            extra_path = extra_path[1:]
        f['filename'] += extra_path
        if f['filename'].endswith('/'):
            if '' in static_files:
                if isinstance(static_files[''], str):
                    f['filename'] += static_files['']
                else:
                    f['filename'] += static_files['']['filename']
                    if 'content_type' in static_files['']:
                        f['content_type'] = static_files['']['content_type']
            else:
                f['filename'] += 'index.html'
        if 'content_type' not in f:
            ext = f['filename'].rsplit('.')[-1]
            f['content_type'] = content_types.get(
                ext, 'application/octet-stream')
    return f
