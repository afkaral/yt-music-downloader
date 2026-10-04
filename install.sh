#!/bin/bash
set -e

echo "Trying to find OS..."

# Read os-release file to determine the OS and its distribution
if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO=$ID
    LIKE=$ID_LIKE
else
    DISTRO="unknown"
    LIKE="unknown"
fi

echo "OS: $DISTRO ($LIKE)"

# Arch
if [[ "$DISTRO" =~ ^(arch|cachyos|manjaro|endeavouros)$ ]] || [[ "$LIKE" =~ arch ]]; then
    echo "It seems like u are using arch by the way. Installing via PKGBUILD script..."
    if [ -f "packaging/arch/PKGBUILD" ]; then
        cd packaging/arch
        makepkg -si --noconfirm
        exit 0
    fi

# Debian
elif [[ "$DISTRO" =~ ^(debian|ubuntu|pop|mint)$ ]] || [[ "$LIKE" =~ debian|ubuntu ]]; then
    echo "building ..."
    if [ -f "packaging/debian/build-deb.sh" ]; then
        bash packaging/debian/build-deb.sh
        DEB_FILE=$(ls music-downloader_*.deb 2>/dev/null | tail -n 1)
        if [ -n "$DEB_FILE" ]; then
            echo "Package installing: $DEB_FILE"
            sudo dpkg -i "$DEB_FILE" || sudo apt-get install -f -y
            exit 0
        fi
    fi

# NixOS
elif [ "$DISTRO" = "nixos" ] || command -v nix &> /dev/null; then
    echo "building ..."
    if [ -f "packaging/nix/flake.nix" ]; then
        nix build .#default
        exit 0
    fi
fi

# Fallback to pip
echo "There is no 'apt-get' or 'dnf' command available on your system."
echo "Installing via pip..."

if command -v pip &> /dev/null; then
    pip install -e .
    echo "Installation completed successfully."
else
    echo "Error: there is no 'pip' command available on your system."
    exit 1
fi
