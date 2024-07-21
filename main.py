import os
import socket
import json
import logging
import multiprocessing
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import unquote, parse_qs
from datetime import datetime
from pymongo import MongoClient, errors

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class CustomHTTPRequestHandler(SimpleHTTPRequestHandler):
    static_files_dir = '/app/public/static'
    pages_dir = '/app/public/pages'

    def translate_path(self, path):
        path = unquote(path)
        if path.startswith('/static/'):
            return os.path.join(self.static_files_dir, path[len('/static/'):])
        elif path.startswith('/pages/'):
            return os.path.join(self.pages_dir, path[len('/pages/'):])
        else:
            return super().translate_path(path)

    def do_GET(self):
        if self.path == '/':
            self.path = '/pages/index.html'
        elif self.path == '/message':
            self.path = '/pages/message.html'
        elif self.path.startswith('/static/'):
            pass
        else:
            self.path = '/pages' + self.path
        return super().do_GET()

    def do_POST(self):
        try:
            if self.path == '/message':
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length).decode('utf-8')

                logging.info("Sending data to socket server")
                send_to_socket_server(post_data)
                logging.info("Received response from socket server")

                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                with open('public/pages/sent.html', "rb") as fd:
                    self.wfile.write(fd.read())
        except Exception as e:
            logging.error(f"Internal server error: {str(e)}")
            self.send_error(500, f"Internal server error: {str(e)}")


def send_to_socket_server(raw_data):
    try:
        if raw_data.startswith('{') and raw_data.endswith('}'):
            post_data = json.loads(raw_data)
        else:
            post_data = parse_qs(raw_data)
            post_data = {k: v[0] for k, v in post_data.items()}

        formatted_data = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "username": post_data.get("username", "anonymous"),
            "message": post_data.get("message", "")
        }

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(('localhost', 5000))
            sock.sendall(bytes(json.dumps(formatted_data), 'utf-8'))
            response = sock.recv(1024)
        return response
    except Exception as e:
        logging.error(f"Error connecting to socket server: {str(e)}")
        return json.dumps({"error": "Error connecting to socket server"}).encode('utf-8')


def handle_client_connection(client_socket):
    try:
        data = client_socket.recv(1024).decode('utf-8')
        logging.info(f"Received data: {data}")

        try:
            message_data = json.loads(data)

            if not isinstance(message_data, dict):
                raise ValueError("Expected a JSON object")

            client = MongoClient('mongodb://mongodb:27017/')
            db = client['messages_database']
            collection = db['messages']
            collection.insert_one(message_data)
            logging.info("Data inserted into MongoDB")

            response = json.dumps({"status": "Data received and stored"})
        except json.JSONDecodeError:
            logging.error("Invalid JSON format received")
            response = json.dumps({"error": "Invalid JSON format"})
        except ValueError as ve:
            logging.error(f"Data format error: {str(ve)}")
            response = json.dumps({"error": "Data format error"})
        except errors.ConnectionFailure as e:
            logging.error(f"Database connection error: {str(e)}")
            response = json.dumps({"error": f"Database connection error: {str(e)}"})

        client_socket.sendall(response.encode('utf-8'))
    finally:
        client_socket.close()


def run_http_server():
    server_address = ('', 3000)
    httpd = HTTPServer(server_address, CustomHTTPRequestHandler)
    logging.info(f'The HTTP server is running. Click to open page: http://localhost:3000/')
    httpd.serve_forever()


def run_socket_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(('', 5000))
    server_socket.listen()
    logging.info(f"Socket server listening on port 5000")

    try:
        while True:
            client_socket, _ = server_socket.accept()
            handle_client_connection(client_socket)
    finally:
        server_socket.close()


def main():
    http_process = multiprocessing.Process(target=run_http_server)
    socket_process = multiprocessing.Process(target=run_socket_server)

    http_process.start()
    socket_process.start()

    http_process.join()
    socket_process.join()


if __name__ == "__main__":
    main()
