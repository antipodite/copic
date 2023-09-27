import socket

PORT = 9999


def main():
    """Test TCP Socket Client."""
    # create an INET, STREAMing socket, this is TCP
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:

        # connect to the server
        sock.connect(("localhost", PORT))

        # send a message
        message = "ccrippey"
        sock.sendall(message.encode('utf-8'))


if __name__ == "__main__":
    main()
