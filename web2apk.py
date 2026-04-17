#!/usr/bin/env python3
"""
web2apk.py - Package any website into an Android APK.
Supports both standalone (downloads toolchain automatically) and
pre-installed / Docker mode (WEB2APK_NO_DOWNLOAD=1).
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

JDK_URL = os.environ.get("JDK_URL", "https://aka.ms/download-jdk/microsoft-jdk-17-linux-x64.tar.gz")
CMDLINE_TOOLS_URL = os.environ.get("CMDLINE_TOOLS_URL", "https://dl.google.com/android/repository/commandlinetools-linux-10406996_latest.zip")
GRADLE_DIST_URL = os.environ.get("GRADLE_DIST_URL", "https://mirrors.cloud.tencent.com/gradle/gradle-7.5-bin.zip")
AGP_VERSION = "7.4.2"
COMPILE_SDK = 33
TARGET_SDK = 33
MIN_SDK = 21
BUILD_TOOLS = "33.0.0"

OFFLINE_MODE = os.environ.get("WEB2APK_NO_DOWNLOAD") == "1"


def download(url: str, dest: Path, desc: str):
    if OFFLINE_MODE:
        return
    if dest.exists():
        print(f"[skip] {desc} already downloaded.")
        return
    print(f"[down] {desc} ...")
    result = subprocess.run(
        ["curl", "-fSL", "--progress-bar", "-o", str(dest), url],
        stdout=sys.stderr,
    )
    if result.returncode != 0:
        if dest.exists():
            dest.unlink()
        raise RuntimeError(f"Failed to download {desc}")
    print(f"[ok  ] Downloaded {desc}")


def extract(archive: Path, dest: Path, desc: str):
    if dest.exists() and any(dest.iterdir()):
        print(f"[skip] {desc} already extracted.")
        return
    print(f"[extr] {desc} ...")
    dest.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(dest)
    elif archive.suffixes == [".tar", ".gz"]:
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(dest)
    else:
        raise RuntimeError(f"Unknown archive format: {archive}")
    print(f"[ok  ] Extracted {desc}")


def find_single_subdir(parent: Path) -> Path:
    entries = [e for e in parent.iterdir() if e.is_dir()]
    if len(entries) != 1:
        raise RuntimeError(f"Expected exactly one subdirectory in {parent}, got {entries}")
    return entries[0]


def setup_jdk(workspace: Path) -> Path:
    jdk_dir = workspace / "jdk"
    if not (jdk_dir / "bin" / "java").exists():
        if OFFLINE_MODE:
            raise RuntimeError(f"Offline mode: JDK not found at {jdk_dir}")
        jdk_archive = workspace / "jdk.tar.gz"
        download(JDK_URL, jdk_archive, "OpenJDK 17")
        tmp_extract = workspace / "_extract_jdk"
        if tmp_extract.exists():
            shutil.rmtree(tmp_extract)
        extract(jdk_archive, tmp_extract, "OpenJDK 17")
        extracted = find_single_subdir(tmp_extract)
        extracted.rename(jdk_dir)
        shutil.rmtree(tmp_extract)
    java_bin = jdk_dir / "bin" / "java"
    print(f"[ok  ] JDK ready: {java_bin}")
    return jdk_dir


def setup_android_sdk(workspace: Path) -> Path:
    sdk_dir = workspace / "android-sdk"
    if not (sdk_dir / "cmdline-tools" / "latest" / "bin" / "sdkmanager").exists():
        if OFFLINE_MODE:
            raise RuntimeError(f"Offline mode: Android SDK not found at {sdk_dir}")
        cmdline_archive = workspace / "cmdline-tools.zip"
        download(CMDLINE_TOOLS_URL, cmdline_archive, "Android cmdline-tools")
        tmp_extract = workspace / "_extract_cmdline"
        if tmp_extract.exists():
            shutil.rmtree(tmp_extract)
        extract(cmdline_archive, tmp_extract, "Android cmdline-tools")
        extracted = find_single_subdir(tmp_extract)
        target = sdk_dir / "cmdline-tools" / "latest"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        extracted.rename(target)
        shutil.rmtree(tmp_extract)

    sdkmanager = sdk_dir / "cmdline-tools" / "latest" / "bin" / "sdkmanager"
    for script in (sdkmanager, sdk_dir / "cmdline-tools" / "latest" / "bin" / "avdmanager"):
        if script.exists():
            os.chmod(script, 0o755)
    print(f"[ok  ] sdkmanager ready: {sdkmanager}")

    env = os.environ.copy()
    env["ANDROID_SDK_ROOT"] = str(sdk_dir)
    env["JAVA_HOME"] = str(workspace / "jdk")
    env["PATH"] = f"{env['JAVA_HOME']}/bin:{env['PATH']}"

    license_marker = sdk_dir / "licenses" / "android-sdk-license"
    if not license_marker.exists():
        if OFFLINE_MODE:
            raise RuntimeError(f"Offline mode: Android SDK licenses not accepted at {license_marker}")
        print("[info] Accepting Android SDK licenses ...")
        subprocess.run([str(sdkmanager), "--licenses"],
                       env=env, input=b"y\n" * 20,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    platform_marker = sdk_dir / "platforms" / f"android-{COMPILE_SDK}"
    buildtools_marker = sdk_dir / "build-tools" / BUILD_TOOLS
    if not platform_marker.exists() or not buildtools_marker.exists():
        if OFFLINE_MODE:
            raise RuntimeError(f"Offline mode: Android platform {COMPILE_SDK} or build-tools {BUILD_TOOLS} missing")
        print(f"[info] Installing Android platform {COMPILE_SDK} and build-tools {BUILD_TOOLS} ...")
        subprocess.run(
            [str(sdkmanager), f"platforms;android-{COMPILE_SDK}", f"build-tools;{BUILD_TOOLS}"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True,
        )
    print(f"[ok  ] Android SDK ready: {sdk_dir}")
    return sdk_dir


def setup_gradle(workspace: Path) -> Path:
    gradle_dir = workspace / "gradle-7.5"
    gradle_bin = gradle_dir / "bin" / "gradle"
    if not gradle_bin.exists():
        if OFFLINE_MODE:
            raise RuntimeError(f"Offline mode: Gradle not found at {gradle_dir}")
        gradle_archive = workspace / "gradle.zip"
        download(GRADLE_DIST_URL, gradle_archive, "Gradle 7.5")
        tmp_extract = workspace / "_extract_gradle"
        if tmp_extract.exists():
            shutil.rmtree(tmp_extract)
        extract(gradle_archive, tmp_extract, "Gradle 7.5")
        extracted = find_single_subdir(tmp_extract)
        extracted.rename(gradle_dir)
        shutil.rmtree(tmp_extract)
    os.chmod(gradle_dir / "bin" / "gradle", 0o755)
    print(f"[ok  ] Gradle ready: {gradle_dir / 'bin' / 'gradle'}")
    return gradle_dir


def write_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_project(workspace: Path, url: str, app_name: str, package: str):
    proj = workspace / "project"
    if proj.exists():
        shutil.rmtree(proj)
    proj.mkdir(parents=True)

    package_path = "/".join(package.split("."))
    safe_url = url.replace('"', '\\"')

    write_text(proj / "build.gradle", f"""\
buildscript {{
    repositories {{
        google()
        mavenCentral()
    }}
    dependencies {{
        classpath 'com.android.tools.build:gradle:{AGP_VERSION}'
    }}
}}

allprojects {{
    repositories {{
        google()
        mavenCentral()
    }}
}}
""")

    write_text(proj / "settings.gradle", "rootProject.name = 'Web2Apk'\ninclude ':app'\n")

    write_text(proj / "gradle.properties", """\
org.gradle.jvmargs=-Xmx256m -Dfile.encoding=UTF-8
org.gradle.parallel=false
org.gradle.caching=false
org.gradle.daemon=false
android.useAndroidX=false
android.enableJetifier=false
""")

    write_text(proj / "local.properties", f"sdk.dir={workspace / 'android-sdk'}\n")

    write_text(proj / "app" / "build.gradle", f"""\
apply plugin: 'com.android.application'

android {{
    compileSdk {COMPILE_SDK}
    buildToolsVersion "{BUILD_TOOLS}"
    namespace '{package}'

    defaultConfig {{
        applicationId "{package}"
        minSdk {MIN_SDK}
        targetSdk {TARGET_SDK}
        versionCode 1
        versionName "1.0"
    }}

    buildTypes {{
        release {{
            minifyEnabled false
            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'), 'proguard-rules.pro'
        }}
    }}
    compileOptions {{
        sourceCompatibility JavaVersion.VERSION_1_8
        targetCompatibility JavaVersion.VERSION_1_8
    }}
}}
""")

    write_text(proj / "app" / "proguard-rules.pro", "")

    write_text(proj / "app" / "src" / "main" / "AndroidManifest.xml", f"""\
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{package}">

    <uses-permission android:name="android.permission.INTERNET" />

    <application
        android:allowBackup="true"
        android:label="@string/app_name"
        android:theme="@android:style/Theme.NoTitleBar">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:configChanges="orientation|screenSize|keyboardHidden">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
""")

    write_text(proj / "app" / "src" / "main" / "res" / "values" / "strings.xml", f"""\
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">{app_name}</string>
</resources>
""")

    write_text(proj / "app" / "src" / "main" / "res" / "layout" / "activity_main.xml", """\
<?xml version="1.0" encoding="utf-8"?>
<RelativeLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent"
    android:layout_height="match_parent">

    <ProgressBar
        android:id="@+id/progressbar"
        style="?android:attr/progressBarStyleHorizontal"
        android:layout_width="match_parent"
        android:layout_height="3dp"
        android:layout_alignParentTop="true"
        android:visibility="gone" />

    <WebView
        android:id="@+id/webview"
        android:layout_width="match_parent"
        android:layout_height="match_parent"
        android:layout_below="@id/progressbar" />
</RelativeLayout>
""")

    main_activity = proj / "app" / "src" / "main" / "java" / package_path / "MainActivity.java"
    write_text(main_activity, f"""\
package {package};

import android.app.Activity;
import android.os.Bundle;
import android.view.View;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.ProgressBar;

public class MainActivity extends Activity {{
    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        final ProgressBar progressBar = findViewById(R.id.progressbar);
        webView = findViewById(R.id.webview);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);

        webView.setWebChromeClient(new WebChromeClient() {{
            @Override
            public void onProgressChanged(WebView view, int newProgress) {{
                progressBar.setProgress(newProgress);
                progressBar.setVisibility(newProgress == 100 ? View.GONE : View.VISIBLE);
            }}
        }});

        webView.setWebViewClient(new WebViewClient() {{
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {{
                return false;
            }}
        }});

        webView.loadUrl("{safe_url}");
    }}

    @Override
    public void onBackPressed() {{
        if (webView != null && webView.canGoBack()) {{
            webView.goBack();
        }} else {{
            super.onBackPressed();
        }}
    }}
}}
""")
    print(f"[ok  ] Project created: {proj}")
    return proj


def build_apk(workspace: Path) -> Path:
    proj = workspace / "project"
    gradle = workspace / "gradle-7.5" / "bin" / "gradle"
    env = os.environ.copy()
    env["JAVA_HOME"] = str(workspace / "jdk")
    env["ANDROID_SDK_ROOT"] = str(workspace / "android-sdk")
    env["PATH"] = f"{env['JAVA_HOME']}/bin:{env['PATH']}"
    env["GRADLE_OPTS"] = "-Xmx256m"
    env["_JAVA_OPTIONS"] = "-Xmx256m"

    print("[build] Running Gradle assembleDebug ...")
    result = subprocess.run(
        [str(gradle), "--no-daemon", "assembleDebug"],
        cwd=str(proj),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    apk = proj / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if apk.exists() and result.returncode == 0:
        print(f"[ok  ] APK built: {apk}")
        return apk
    else:
        raise RuntimeError(f"Gradle build failed (rc={result.returncode}):\n{result.stdout}")


def main():
    parser = argparse.ArgumentParser(description="Package a website into an Android APK")
    parser.add_argument("--url", required=True, help="Website URL to package")
    parser.add_argument("--name", default="WebApp", help="App display name")
    parser.add_argument("--package", default="com.example.webapp", help="Java package name")
    parser.add_argument("--output", default=".", help="Output directory for the APK")
    parser.add_argument("--workspace", default="web2apk_workspace", help="Workspace directory")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    setup_jdk(workspace)
    setup_android_sdk(workspace)
    setup_gradle(workspace)
    create_project(workspace, args.url, args.name, args.package)
    apk = build_apk(workspace)

    out_dir = Path(args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_apk = out_dir / f"{args.name.replace(' ', '_')}-debug.apk"
    shutil.copy(apk, out_apk)
    print(f"\nSuccess! APK saved to: {out_apk}")


if __name__ == "__main__":
    main()
