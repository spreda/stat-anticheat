#!/usr/bin/env python3
"""
Report Generator Framework - Setup Script

Установка окружения для генерации отчётов.
"""

import subprocess
import sys
import os

def check_python():
    """Check Python version."""
    print(f"Python version: {sys.version}")
    if sys.version_info < (3, 8):
        print("ERROR: Python 3.8+ required")
        sys.exit(1)

def install_packages():
    """Install required packages."""
    packages = ["python-docx", "lxml"]
    print(f"Installing packages: {', '.join(packages)}")
    subprocess.check_call([sys.executable, "-m", "pip", "install"] + packages)

def create_directories():
    """Create required directories."""
    dirs = ["templates", "input", "project/screenshots", "project/diagrams", "output"]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        print(f"Created: {d}")

def main():
    print("=" * 60)
    print("  Report Generator Framework - Setup")
    print("=" * 60)
    
    check_python()
    install_packages()
    create_directories()
    
    print("\nSetup complete!")
    print("\nNext steps:")
    print("1. Copy your university template to: templates/Шаблон для ДР.docx")
    print("2. Copy your current draft to: input/Дипломная_работа.docx (optional)")
    print("3. Copy project code to: project/")
    print("4. Copy screenshots to: project/screenshots/")
    print("5. Copy diagrams to: project/diagrams/")
    print("6. Edit config.json with your details")
    print("7. Run: python utils/generate_diploma.py")

if __name__ == "__main__":
    main()
