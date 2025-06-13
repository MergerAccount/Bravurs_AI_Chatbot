from flask import request

def get_client_ip() -> str:
    """
    Retrieves the client's IP address, checking for X-Forwarded-For header
    if the application is behind a proxy.
    
    Returns:
        str: The client's IP address
    """
    x_forwarded_for = request.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.remote_addr 