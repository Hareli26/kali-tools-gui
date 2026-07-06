# Kali Tools GUI - app image (Kali base so pentest tools are available via apt)
FROM kalilinux/kali-rolling

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 ca-certificates \
      nmap nikto hydra sqlmap dnsenum dnsrecon whatweb wafw00f dnsutils whois \
      nbtscan smbclient john sslscan gobuster exiftool binwalk \
      netcat-traditional iputils-ping wget dirb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Runtime data (learning, activity, audit, reports) goes to a mountable volume.
ENV KALIGUI_HOST=0.0.0.0 \
    KALIGUI_PORT=8777 \
    KALIGUI_DATA_DIR=/data
RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8777

# In compose the app is only reachable on the internal network (never published).
CMD ["python3", "server.py"]
