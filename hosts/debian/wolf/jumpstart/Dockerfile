# Wine (32-bit) runner for the JumpStart CD-ROM games, packaged as a Games on
# Whales / Wolf app. Game data and Wine prefixes live on the host and are
# bind-mounted by Wolf (see README.md).
FROM ghcr.io/games-on-whales/base-app:edge

ENV DEBIAN_FRONTEND=noninteractive
RUN dpkg --add-architecture i386 \
 && apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates wget gnupg \
 && mkdir -pm755 /etc/apt/keyrings \
 && wget -qO- https://dl.winehq.org/wine-builds/winehq.key | gpg --dearmor -o /etc/apt/keyrings/winehq-archive.key \
 && wget -qNP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/plucky/winehq-plucky.sources \
 && apt-get update \
 && apt-get install -y --install-recommends winehq-stable \
 && apt-get install -y --no-install-recommends \
      libgl1:i386 libgl1-mesa-dri:i386 libpulse0:i386 libasound2-plugins:i386 \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --chmod=755 js-run.sh /usr/local/bin/js-run
COPY --chmod=755 startup-app.sh /opt/gow/startup-app.sh

ENV WINEARCH=win32 WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
ENTRYPOINT ["/entrypoint.sh"]
