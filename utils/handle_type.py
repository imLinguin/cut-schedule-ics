def handle_type(summary):
    lower_summary = summary.lower()

    if "wykład" in lower_summary:
        return "wykład"
    elif "ćwiczenia" in lower_summary:
        return "ćwiczenia"
    elif "laboratorium" in lower_summary:
        return "laboratorium"
    elif "seminarium" in lower_summary:
        return "seminarium"
    elif "projekt" in lower_summary:
        return "projekt"
    elif "konsultacje" in lower_summary:
        return "konsultacje"
