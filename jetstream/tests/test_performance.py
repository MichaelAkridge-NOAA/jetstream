import pytest
from jetstream.services import FileFilter

def test_file_filter_include_patterns():
    # Test only include patterns
    ff = FileFilter(include_patterns=["*.jpg", "*.png"], exclude_patterns=[], exclude_folders=[])
    assert ff.should_include_filename("test.jpg") is True
    assert ff.should_include_filename("test.png") is True
    assert ff.should_include_filename("test.txt") is False

def test_file_filter_exclude_patterns():
    # Test only exclude patterns
    ff = FileFilter(include_patterns=[], exclude_patterns=["*.tmp", "*.bak"], exclude_folders=[])
    assert ff.should_include_filename("test.jpg") is True
    assert ff.should_include_filename("test.tmp") is False
    assert ff.should_include_filename("test.bak") is False

def test_file_filter_combined_patterns():
    # Test both include and exclude
    ff = FileFilter(include_patterns=["*.jpg", "*.png"], exclude_patterns=["temp*"], exclude_folders=[])
    assert ff.should_include_filename("photo.jpg") is True
    assert ff.should_include_filename("temp_photo.jpg") is False
    assert ff.should_include_filename("image.png") is True
    assert ff.should_include_filename("temp.png") is False
    assert ff.should_include_filename("data.csv") is False

def test_file_filter_exclude_folders():
    ff = FileFilter(exclude_folders=["_archive", "temp"])
    assert ff.should_exclude_folder("_archive") is True
    assert ff.should_exclude_folder("temp") is True
    assert ff.should_exclude_folder("data") is False

def test_file_filter_case_insensitivity():
    ff = FileFilter(include_patterns=["*.JPG"], exclude_patterns=["TEMP*"])
    assert ff.should_include_filename("IMAGE.JPG") is True
    assert ff.should_include_filename("image.jpg") is True
    assert ff.should_include_filename("TEMP.JPG") is False
    assert ff.should_include_filename("temp.jpg") is False

def test_file_filter_regex_passthrough():
    # Test patterns that are already regex
    ff = FileFilter(include_patterns=[r".*\.tiff?$"])
    assert ff.should_include_filename("test.tif") is True
    assert ff.should_include_filename("test.tiff") is True
    assert ff.should_include_filename("test.jpg") is False

def test_file_filter_empty_patterns():
    ff = FileFilter(include_patterns=[], exclude_patterns=[], exclude_folders=[])
    assert ff.should_include_filename("anything.txt") is True
    assert ff.should_exclude_folder("anything") is False
