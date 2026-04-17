FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    python3 python3-pip curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pre-install JDK, Android SDK and Gradle to /opt
WORKDIR /opt

# 1. JDK 17
RUN curl -fSL -o jdk.tar.gz "https://aka.ms/download-jdk/microsoft-jdk-17-linux-x64.tar.gz" && \
    tar -xzf jdk.tar.gz && \
    rm jdk.tar.gz && \
    mv jdk-17* jdk || true

# 2. Android SDK command line tools
RUN curl -fSL -o cmdline-tools.zip "https://dl.google.com/android/repository/commandlinetools-linux-10406996_latest.zip" && \
    unzip -q cmdline-tools.zip && \
    rm cmdline-tools.zip && \
    mkdir -p android-sdk/cmdline-tools && \
    mv cmdline-tools latest && \
    mv latest android-sdk/cmdline-tools/ && \
    chmod +x android-sdk/cmdline-tools/latest/bin/sdkmanager

# 3. Gradle 7.5
RUN curl -fSL -o gradle.zip "https://mirrors.cloud.tencent.com/gradle/gradle-7.5-bin.zip" && \
    unzip -q gradle.zip && \
    rm gradle.zip

ENV JAVA_HOME=/opt/jdk
ENV ANDROID_SDK_ROOT=/opt/android-sdk
ENV PATH=$JAVA_HOME/bin:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$PATH:/opt/gradle-7.5/bin

# 4. Accept licenses and install required SDK components
RUN yes | sdkmanager --licenses && \
    sdkmanager "platforms;android-33" "build-tools;33.0.0"

# 5. Create workspace symlinks expected by web2apk.py
RUN mkdir -p /opt/web2apk_workspace && \
    ln -s /opt/jdk /opt/web2apk_workspace/jdk && \
    ln -s /opt/android-sdk /opt/web2apk_workspace/android-sdk && \
    ln -s /opt/gradle-7.5 /opt/web2apk_workspace/gradle-7.5

# 6. Copy web2apk.py and run a warm-up build so Gradle dependencies are cached
COPY web2apk.py /app/web2apk.py
WORKDIR /app
RUN WEB2APK_NO_DOWNLOAD=1 python3 web2apk.py \
    --url https://example.com \
    --name WarmUp \
    --package com.example.warmup \
    --workspace /opt/web2apk_workspace \
    --output /tmp && \
    rm -rf /tmp/WarmUp-debug.apk /opt/web2apk_workspace/project

# 7. Copy FastAPI app and install deps
COPY app /app/app
RUN pip3 install --no-cache-dir -r app/requirements.txt

ENV WEB2APK_NO_DOWNLOAD=1
ENV TOOLS_DIR=/opt/web2apk_workspace
ENV WORKSPACE_DIR=/tmp/web2apk_workspace
ENV BUILD_DIR=/tmp/builds

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
