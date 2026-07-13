DEFAULT_COLUMNS = [
    "PaperID", "Topic", "Title", "Filename", "Path", "Status", "Notes",
    "Year", "Authors", "Venue", "DOI", "BibKey", "Abstract", "Keywords",
    "FileState", "SHA256", "OriginalPath", "ArchivedAt", "AddedDate", "ModifiedDate",
]
IGNORED_DIRS = {".paper_manager", ".git", "__pycache__"}
ALLOWED_STATUSES = {"OK", "Needs Review", "Priority", "Read", "Ignore", "Cited"}
