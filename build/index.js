function copyUrl(e) {
    e.preventDefault();
    const url = 'https://planpk.linguin.dev' + e.target.dataset.calUrl;
    window.navigator.clipboard.writeText(url).then(() => alert(`Link skopiowany do schowka`))
}
const copyLinks = document.querySelectorAll('a[data-cal-url]');
for (const copyLink of copyLinks) {
    copyLink.addEventListener('click', copyUrl);
}
