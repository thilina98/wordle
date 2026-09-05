"""Run the API: python -m wordle"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "wordle.app:create_app",
        factory=True,
        host="::",  # dual-stack: serves IPv6 and IPv4
        port=8000,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
