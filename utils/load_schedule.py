from bs4 import BeautifulSoup
import requests
import urllib.parse
import os
import hashlib

WEB_PAGE = "https://it.pk.edu.pl/studenci/na-studiach/rozklady-zajec/"


def load_schedule():
    session = requests.session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (X11; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0"
    )
    retry = 5
    while retry > 0:
        try:
            res = session.get(WEB_PAGE)
            break
        except Exception:
            retry -= 1
            if retry == 0:
                raise
            print("Retrying...")
            continue
    body = res.content
    existing_hash = None
    if os.path.exists("excel.xls"):
        existing_hash = hashlib.md5()
        with open("excel.xls", "rb") as f:
            while data := f.read(1024):
                existing_hash.update(data)
            existing_hash = existing_hash.hexdigest()

    soup = BeautifulSoup(body, "html.parser")
    links = soup.find_all("a")

    found_link = None
    for link in links:
        if "Kierunek: Informatyka" in link.get_text():
            found_link = link.get("href")

    if not found_link:
        print("Failed to get a link")
        return

    if "sharepoint.com" in str(found_link):
        parsed_link = urllib.parse.urlparse(str(found_link))
        query = urllib.parse.parse_qsl(parsed_link.query)
        query.append(("download", "1"))
        query = urllib.parse.urlencode(query)
        parsed_link = parsed_link._replace(query=query)
        found_link = urllib.parse.urlunparse(parsed_link)

    print("Getting", found_link)
    url = str(found_link)
    res = session.get(url, allow_redirects=True)
    excel_file = res.content
    new_hash = hashlib.md5(excel_file).hexdigest()
    print(f"::notice::Cached file hash is {existing_hash}")
    print(f"::notice::Downloaded file hash is {new_hash}")
    with open("excel.xls", "wb") as f:
        f.write(excel_file)
    if "CI" in os.environ and existing_hash and existing_hash == new_hash:
        print(f"::notice::Files are the same, skipping deployment")
        exit(1)
