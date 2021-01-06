import ujson as json
import uos as os
import usocket as socket

def http_get_async(url):
    _, _, host, path = url.split('/', 3)
    if ':' in host:
        host, port = host.split(':')
    else:
        port = 80
    addr = socket.getaddrinfo(host, port)[0][-1]
    s = socket.socket()
    s.connect(addr)
    s.send(bytes('GET /%s HTTP/1.0\r\nHost: %s\r\n\r\n' % (path, host),
                 'utf8'))
    started = False
    header_str = b''
    headers = {}
    while True:
        data = s.recv(1000)
        if data:
            body_bytes = data
            if not started and b'HTTP' in body_bytes:
                started = True
                continue
            buffer = header_str + body_bytes
            if not headers and not b'\r\n\r\n' in buffer:
                header_str += body_bytes
                continue
            if b'\r\n\r\n' in buffer:
                headers, body_bytes = buffer.split(b'\r\n\r\n')
            if body_bytes:
                yield body_bytes
        else:
            break

def http_get(url):
    response = b''
    try:
        get = http_get_async(url)
        while True:
            file_bytes = get.send(None)
            response += file_bytes
    except StopIteration:
        pass

    response_str = str(response, 'utf-8')
    return response_str

def ensure_dirs(path):
    split_path = path.split('/')
    if len(split_path) > 1:
        for i, fragment in enumerate(split_path):
            parent = '/'.join(split_path[:-i])
            try:
                os.mkdir(parent)
            except OSError:
                pass

def http_get_to_file(url, path):
    ensure_dirs(path)
    with open(path, 'w') as outfile:
        try:
            get = http_get_async(url)
            while True:
                file_bytes = get.send(None)
                outfile.write(file_bytes)
        except StopIteration:
            outfile.close()