from bs4 import BeautifulSoup
import datetime


def generate_html(cals, groups):
    with open("index.html", "r") as f:
        soup = BeautifulSoup(f, "html.parser")
        if soup.body is None:
            raise RuntimeError("Expected HTML to contain a <body> element")
        ul = None
        prev_semester = None
        prev_degree = None
        for group_i in range(len(groups)):
            degree, semester, practice_group, lab_group, _identifier = groups[group_i]
            cal = cals[group_i]

            if semester != prev_semester:
                prev_semester = semester
                if ul:
                    soup.body.append(ul)
                if degree != prev_degree:
                    prev_degree = degree
                    h2 = soup.new_tag("h2")
                    h2.string = degree
                    soup.body.append(h2)
                h3 = soup.new_tag("h3")
                h3.string = semester
                soup.body.append(h3)
                ul = soup.new_tag("ul")
            li = soup.new_tag("li")
            if practice_group.isnumeric():
                li.string = f"Grupa ćwiczeniowa {practice_group} grupa laboratoryjna {lab_group}"
            else:
                li.string = f"Grupa {_identifier[:-2]}"
            # Create a link to download
            a_tag = soup.new_tag("a")
            a_tag.attrs["href"] = "/" + cal
            a_tag.string = cal
            li.append(a_tag)

            # Create a subscription link (supported by some email clients)
            sup_tag = soup.new_tag("sup")
            a_tag = soup.new_tag("a")
            a_tag.attrs["href"] = "webcal://planpk.linguin.dev/" + cal
            a_tag.string = "subskrybuj"
            sup_tag.append(a_tag)
            li.append(sup_tag)

            sup_tag = soup.new_tag("sup")
            a_tag = soup.new_tag("a")
            a_tag.attrs["href"] = "#"
            a_tag.attrs["class"] = "link-copy"
            a_tag.attrs["data-cal-url"] = "/" + cal
            a_tag.string = "kopiuj link"
            sup_tag.append(a_tag)
            li.append(sup_tag)
            if ul is None:
                raise RuntimeError(
                    "Unexpected state: ul element not initialized. This may indicate that the groups list is empty or semester data is missing."
                )
            ul.append(li)
        if ul:
            soup.body.append(ul)
        footer = soup.new_tag("footer")
        time = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        p_tag = soup.new_tag("p")
        p_tag.string = f"Ostatnia aktualizacja: {time}"
        repo_link = soup.new_tag("a")
        repo_link.attrs["href"] = "https://github.com/imLinguin/cut-schedule-ics"
        repo_link.string = "GitHub"
        p_tag.append(repo_link)
        footer.append(p_tag)
        soup.body.append(footer)
        with open("build/index.html", "w") as fw:
            fw.write(soup.prettify())
