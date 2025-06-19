#!/usr/bin/env python3
"""
Setup script for Bravur's AI Chatbot
Checks for required system dependencies and provides installation instructions.
"""

import subprocess
import sys
import platform
import os

def check_ffmpeg():
    """Check if ffmpeg is installed and accessible"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("✅ ffmpeg is installed and working")
            return True
        else:
            print("❌ ffmpeg is installed but not working properly")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("❌ ffmpeg is not installed or not in PATH")
        return False
    except Exception as e:
        print(f"❌ Error checking ffmpeg: {e}")
        return False

def get_installation_instructions():
    """Get ffmpeg installation instructions based on the operating system"""
    system = platform.system().lower()
    
    if system == "darwin":  # macOS
        return """
📦 Install ffmpeg on macOS:
   brew install ffmpeg

   If you don't have Homebrew installed:
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
"""
    elif system == "linux":
        # Try to detect the distribution
        try:
            with open('/etc/os-release', 'r') as f:
                content = f.read().lower()
                if 'ubuntu' in content or 'debian' in content:
                    return """
📦 Install ffmpeg on Ubuntu/Debian:
   sudo apt update
   sudo apt install ffmpeg
"""
                elif 'fedora' in content or 'rhel' in content or 'centos' in content:
                    return """
📦 Install ffmpeg on Fedora/RHEL/CentOS:
   sudo dnf install ffmpeg
   # or for older versions:
   sudo yum install ffmpeg
"""
                else:
                    return """
📦 Install ffmpeg on Linux:
   # Ubuntu/Debian:
   sudo apt update && sudo apt install ffmpeg
   
   # Fedora/RHEL/CentOS:
   sudo dnf install ffmpeg
   
   # Or download from: https://ffmpeg.org/download.html
"""
        except:
            return """
📦 Install ffmpeg on Linux:
   # Ubuntu/Debian:
   sudo apt update && sudo apt install ffmpeg
   
   # Fedora/RHEL/CentOS:
   sudo dnf install ffmpeg
   
   # Or download from: https://ffmpeg.org/download.html
"""
    elif system == "windows":
        return """
📦 Install ffmpeg on Windows:
   1. Download from: https://ffmpeg.org/download.html
   2. Extract to a folder (e.g., C:\\ffmpeg)
   3. Add C:\\ffmpeg\\bin to your system PATH
   4. Restart your terminal/command prompt
   
   Alternative (using Chocolatey):
   choco install ffmpeg
   
   Alternative (using Scoop):
   scoop install ffmpeg
"""
    else:
        return """
📦 Install ffmpeg:
   Download from: https://ffmpeg.org/download.html
   Follow the installation instructions for your operating system.
"""

def main():
    """Main setup function"""
    print("🔧 Bravur's AI Chatbot Setup")
    print("=" * 40)
    
    # Check ffmpeg
    print("\n🎵 Checking ffmpeg installation...")
    ffmpeg_ok = check_ffmpeg()
    
    if not ffmpeg_ok:
        print("\n" + get_installation_instructions())
        print("\n⚠️  ffmpeg is required for audio processing (WebM repair and conversion)")
        print("   Please install ffmpeg and run this setup script again.")
        return False
    
    print("\n✅ All system dependencies are installed!")
    print("\n📋 Next steps:")
    print("   1. Make sure you have the .env file in the project root")
    print("   2. Create and activate a virtual environment:")
    print("      python -m venv venv")
    print("      source venv/bin/activate  # On macOS/Linux")
    print("      venv\\Scripts\\activate     # On Windows")
    print("   3. Install Python dependencies:")
    print("      pip install -r requirements.txt")
    print("   4. Run the application:")
    print("      python run.py")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 