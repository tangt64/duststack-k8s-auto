#!/usr/bin/python3.6
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os

server_address = ('0.0.0.0', 8080)
httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
os.chdir('{{ k8s_work_dir }}')  # optional
print('Running server...')
httpd.serve_forever()