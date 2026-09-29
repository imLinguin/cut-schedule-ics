function copyUrl(e) {
    e.preventDefault();
    const link = e.currentTarget;
    const url = 'https://planpk.linguin.dev' + link.dataset.calUrl;
    window.navigator.clipboard.writeText(url).then(() => {
        const text = link.textContent;
        link.textContent = 'Skopiowano!';
        setTimeout(() => (link.textContent = text), 1500);
    }, () => window.prompt('Skopiuj link:', url));
}
const copyLinks = document.querySelectorAll('a[data-cal-url]');
for (const copyLink of copyLinks) {
    copyLink.addEventListener('click', copyUrl);
}
