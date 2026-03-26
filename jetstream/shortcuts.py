"""
Desktop and Start Menu shortcut creation for NOAA JetStream
"""
import sys
import os
from pathlib import Path


def create_shortcuts():
    """Create desktop and start menu shortcuts for JetStream"""
    try:
        # Try using pyshortcuts if available
        import pyshortcuts
        
        # Get the Python executable and script paths
        python_exe = sys.executable
        
        # Create shortcut to launch JetStream
        shortcut_name = "NOAA_JetStream"
        
        # Determine icon path (if you have one)
        icon_path = None
        package_dir = Path(__file__).parent
        possible_icons = [
            package_dir / "static" / "icon.ico",
            package_dir / "static" / "icon.png",
            package_dir.parent / "docs" / "icon.ico",
            package_dir.parent / "docs" / "icon.png",
        ]
        for icon in possible_icons:
            if icon.exists():
                icon_path = str(icon)
                break
        
        print("🔧 Creating shortcuts...")
        print(f"   Python: {python_exe}")
        
        # For Windows, create a simple batch file to avoid conda wrapper issues
        if sys.platform == "win32":
            # Create a batch file launcher
            batch_file = Path.home() / ".jetstream" / "launch_jetstream.bat"
            batch_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Write a simple batch file that directly calls python
            with open(batch_file, 'w') as f:
                f.write('@echo off\n')
                f.write(f'"{python_exe}" -m jetstream.cli\n')
                f.write('pause\n')
            
            # Create shortcut to the batch file (no args needed, batch file has command)
            script_target = str(batch_file)
            print(f"   Created launcher: {batch_file}")
        else:
            # For macOS/Linux, create a shell script wrapper
            script_file = Path.home() / ".jetstream" / "launch_jetstream.sh"
            script_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(script_file, 'w') as f:
                f.write('#!/bin/bash\n')
                f.write(f'"{python_exe}" -m jetstream.cli\n')
            
            # Make it executable
            script_file.chmod(0o755)
            script_target = str(script_file)
            print(f"   Created launcher: {script_file}")
        
        print(f"   Command: {script_target}")
        if icon_path:
            print(f"   Icon: {icon_path}")
        
        # Create shortcut on desktop
        desktop = pyshortcuts.make_shortcut(
            script_target,
            name=shortcut_name,
            description="Launch NOAA JetStream - Cloud Data Manager",
            icon=icon_path,
            terminal=True,
            desktop=True,
            startmenu=True,
        )
        
        print("\n✅ Shortcuts created successfully!")
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
        
        return True
        
    except ImportError:
        print("\n⚠️  pyshortcuts package not found.")
        print("\nTo enable automatic shortcut creation, install it:")
        print("   pip install pyshortcuts")
        print("\nThen run this command again:")
        print("   jetstream-create-shortcuts")
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
        
        shortcut_name = "NOAA_JetStream"
        # pyshortcuts sanitizes the name differently in different contexts
        sanitized_names = [
            "NOAA_JetStream",
            "NOAA-JetStream",
            "NOAA__JetStream",
        ]
        
        print("🔧 Removing shortcuts...")
        
        # Get shortcut locations
        desktop_path = Path.home() / "Desktop"
        
        if sys.platform == "win32":
            try:
                startmenu_path = Path(pyshortcuts.get_startmenu())
            except AttributeError:
                startmenu_path = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            
            shortcuts = [
                desktop_path / f"{shortcut_name}.lnk",
                startmenu_path / f"{shortcut_name}.lnk",
            ]
            
            for sanitized_name in sanitized_names:
                shortcuts.extend([
                    desktop_path / f"{sanitized_name}.lnk",
                    startmenu_path / f"{sanitized_name}.lnk"
                ])
            
            # Also remove the batch launcher
            batch_file = Path.home() / ".jetstream" / "launch_jetstream.bat"
            if batch_file.exists():
                batch_file.unlink()
                print(f"   ✓ Removed launcher: {batch_file}")
                
        elif sys.platform == "darwin":
            shortcuts = [
                desktop_path / f"{shortcut_name}.app",
                Path.home() / "Applications" / f"{shortcut_name}.app",
            ]
            
            for sanitized_name in sanitized_names:
                shortcuts.extend([
                    desktop_path / f"{sanitized_name}.app",
                    Path.home() / "Applications" / f"{sanitized_name}.app"
                ])
            
            script_file = Path.home() / ".jetstream" / "launch_jetstream.sh"
            if script_file.exists():
                script_file.unlink()
                print(f"   ✓ Removed launcher: {script_file}")
                
        else:  # Linux
            shortcuts = [
                desktop_path / f"{shortcut_name}.desktop",
                Path.home() / ".local" / "share" / "applications" / f"{shortcut_name}.desktop"
            ]
            
            for sanitized_name in sanitized_names:
                shortcuts.extend([
                    desktop_path / f"{sanitized_name}.desktop",
                    Path.home() / ".local" / "share" / "applications" / f"{sanitized_name}.desktop"
                ])
            
            script_file = Path.home() / ".jetstream" / "launch_jetstream.sh"
            if script_file.exists():
                script_file.unlink()
                print(f"   ✓ Removed launcher: {script_file}")
        
        removed = False
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
