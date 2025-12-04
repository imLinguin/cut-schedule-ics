import os


def clean_ics():
    for entry in os.listdir("build"):
        if entry.endswith(".ics"):
            os.remove(f"build/{entry}")
