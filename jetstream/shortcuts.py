"""
Desktop and Start Menu shortcut creation for NOAA JetStream
"""
import sys
from pathlib import Path


SHORTCUTS = [
    {
        "name": "NOAA_JetStream",
        "launcher": "launch_jetstream",
        "description": "Launch NOAA JetStream - Cloud Data Manager",
        "icon": "icon",
    },
    {
        "name": "GCloud_Auth_Login",
        "launcher": "gcloud_auth_login",
        "description": "Authenticate Google Cloud for JetStream",
        "icon": "gcloud_auth",
    },
]


def _find_icon(base_name):
    """Find the best packaged icon for a shortcut."""
    package_dir = Path(__file__).parent
    possible_icons = [
        package_dir / "static" / f"{base_name}.ico",
        package_dir / "static" / f"{base_name}.png",
        package_dir.parent / "docs" / f"{base_name}.ico",
        package_dir.parent / "docs" / f"{base_name}.png",
    ]
    for icon in possible_icons:
        if icon.exists():
            return str(icon)
    return None


def _write_launcher(launcher_name, commands):
    launcher_dir = Path.home() / ".jetstream"
    launcher_dir.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        launcher_file = launcher_dir / f"{launcher_name}.bat"
        with open(launcher_file, "w") as f:
            f.write("@echo off\n")
            for command in commands:
                f.write(f"{command}\n")
            f.write("pause\n")
    else:
        launcher_file = launcher_dir / f"{launcher_name}.sh"
        with open(launcher_file, "w") as f:
            f.write("#!/bin/bash\n")
            for command in commands:
                f.write(f"{command}\n")
        launcher_file.chmod(0o755)

    return launcher_file


def _shortcut_name_variants(shortcut_name):
    return {
        shortcut_name,
        shortcut_name.replace("_", "-"),
        shortcut_name.replace("_", "__"),
    }


def create_shortcuts():
    """Create desktop and start menu shortcuts for JetStream"""
    try:
        # Try using pyshortcuts if available
        import pyshortcuts
        
        # Get the Python executable and script paths
        python_exe = sys.executable
        
        print("🔧 Creating shortcuts...")
        print(f"   Python: {python_exe}")

        shortcut_commands = {
            "launch_jetstream": [f'"{python_exe}" -m jetstream.cli'],
            "gcloud_auth_login": ["gcloud auth login"],
        }

        desktops = []
        for shortcut in SHORTCUTS:
            script_target = _write_launcher(
                shortcut["launcher"],
                shortcut_commands[shortcut["launcher"]],
            )
            icon_path = _find_icon(shortcut["icon"])

            print(f"   Created launcher: {script_target}")
            print(f"   Command: {script_target}")
            if icon_path:
                print(f"   Icon: {icon_path}")

            desktop = pyshortcuts.make_shortcut(
                str(script_target),
                name=shortcut["name"],
                description=shortcut["description"],
                icon=icon_path,
                terminal=True,
                desktop=True,
                startmenu=True,
            )
            desktops.append(desktop)
        
        print("\n✅ Shortcuts created successfully!")
        for desktop in desktops:
            print(f"   Desktop: {desktop}")
        
        # Get start menu location (different methods for different versions)
        try:
            startmenu = pyshortcuts.get_startmenu()
        except AttributeError:
            # Fallback for older versions - construct manually
            if sys.platform == "win32":
                startmenu = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            elif sys.platform == "darwin":
                startmenu = Path.home() / "Applications"
            else:
                startmenu = Path.home() / ".local" / "share" / "applications"
        
        print(f"   Start Menu: {startmenu}")
        print("\n💡 You can now launch JetStream from:")
        print("   - Your desktop icon")
        print("   - Start Menu (Windows) or Applications (Mac/Linux)")
        print("   - Command line: jetstream")
        print("\n🔐 You can also authenticate Google Cloud from:")
        print("   - The GCloud Auth Login desktop or Start Menu shortcut")
        
        return True
        
    except ImportError as e:
        # Check if pyshortcuts is installed but missing a sub-dependency (e.g. pywin32)
        try:
            import importlib.util
            if importlib.util.find_spec("pyshortcuts") is not None:
                print("\n⚠️  pyshortcuts is installed but a dependency is missing.")
                print(f"   Error: {e}")
                if sys.platform == "win32" and "pywin32" in str(e):
                    print("\nFix: install the missing Windows dependency:")
                    print("   pip install pywin32")
                else:
                    print("\nFix: reinstall with:")
                    print("   pip install --force-reinstall pyshortcuts")
            else:
                print("\n⚠️  pyshortcuts package not found.")
                print("\nFix: it should have been included. Reinstall the package:")
                print("   pip install --force-reinstall noaa-jetstream")
        except Exception:
            print(f"\n⚠️  Import error: {e}")
        print("\nYou can still run JetStream from the command line:")
        print("   jetstream")
        return False
    except Exception as e:
        print(f"\n❌ Error creating shortcuts: {e}")
        print("\nYou can still run JetStream from the command line:")
        print("   jetstream")
        return False


def remove_shortcuts():
    """Remove desktop and start menu shortcuts for JetStream"""
    try:
        import pyshortcuts
        
        shortcut_names = [shortcut["name"] for shortcut in SHORTCUTS]
        sanitized_names = set()
        for shortcut_name in shortcut_names:
            sanitized_names.update(_shortcut_name_variants(shortcut_name))
        
        print("🔧 Removing shortcuts...")
        
        # Get shortcut locations
        desktop_path = Path.home() / "Desktop"
        removed = False
        
        if sys.platform == "win32":
            try:
                startmenu_path = Path(pyshortcuts.get_startmenu())
            except AttributeError:
                startmenu_path = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            
            shortcuts = []
            
            for sanitized_name in sanitized_names:
                shortcuts.extend([
                    desktop_path / f"{sanitized_name}.lnk",
                    startmenu_path / f"{sanitized_name}.lnk"
                ])
            
            for shortcut in SHORTCUTS:
                batch_file = Path.home() / ".jetstream" / f"{shortcut['launcher']}.bat"
                if batch_file.exists():
                    batch_file.unlink()
                    print(f"   ✓ Removed launcher: {batch_file}")
                    removed = True
                
        elif sys.platform == "darwin":
            shortcuts = []
            
            for sanitized_name in sanitized_names:
                shortcuts.extend([
                    desktop_path / f"{sanitized_name}.app",
                    Path.home() / "Applications" / f"{sanitized_name}.app"
                ])
            
            for shortcut in SHORTCUTS:
                script_file = Path.home() / ".jetstream" / f"{shortcut['launcher']}.sh"
                if script_file.exists():
                    script_file.unlink()
                    print(f"   ✓ Removed launcher: {script_file}")
                    removed = True
                
        else:  # Linux
            shortcuts = []
            
            for sanitized_name in sanitized_names:
                shortcuts.extend([
                    desktop_path / f"{sanitized_name}.desktop",
                    Path.home() / ".local" / "share" / "applications" / f"{sanitized_name}.desktop"
                ])
            
            for shortcut in SHORTCUTS:
                script_file = Path.home() / ".jetstream" / f"{shortcut['launcher']}.sh"
                if script_file.exists():
                    script_file.unlink()
                    print(f"   ✓ Removed launcher: {script_file}")
                    removed = True
        
        for shortcut in shortcuts:
            if shortcut.exists():
                try:
                    shortcut.unlink()
                    print(f"   ✓ Removed: {shortcut}")
                    removed = True
                except Exception as e:
                    print(f"   ✗ Failed to remove {shortcut}: {e}")
        
        if removed:
            print("\n✅ Shortcuts removed successfully!")
        else:
            print("\n⚠️  No shortcuts found to remove.")
            print(f"\nSearched in:")
            print(f"   Desktop: {desktop_path}")
            if sys.platform == "win32":
                print(f"   Start Menu: {startmenu_path}")
        
        return True
        
    except ImportError:
        print("\n⚠️  pyshortcuts package not found.")
        print("No shortcuts to remove.")
        return False
    except Exception as e:
        print(f"\n❌ Error removing shortcuts: {e}")
        return False


def main_create():
    """Entry point for creating shortcuts"""
    print("\n" + "=" * 60)
    print("  🚀 NOAA JetStream - Shortcut Creator")
    print("=" * 60 + "\n")
    create_shortcuts()


def main_remove():
    """Entry point for removing shortcuts"""
    print("\n" + "=" * 60)
    print("  🚀 NOAA JetStream - Shortcut Remover")
    print("=" * 60 + "\n")
    remove_shortcuts()


if __name__ == "__main__":
    main_create()
