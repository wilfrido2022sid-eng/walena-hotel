(() => {
    const cards = Array.from(document.querySelectorAll('[data-lightbox-group]'));
    if (!cards.length) return;

    const lightbox = document.createElement('div');
    lightbox.className = 'walena-lightbox';
    lightbox.setAttribute('role', 'dialog');
    lightbox.setAttribute('aria-modal', 'true');
    lightbox.setAttribute('aria-label', 'Galería de imágenes');
    lightbox.setAttribute('aria-hidden', 'true');
    lightbox.innerHTML = `
        <div class="walena-lightbox__layout">
            <div class="walena-lightbox__stage">
                <span class="walena-lightbox__counter" aria-live="polite"></span>
                <button class="walena-lightbox__arrow walena-lightbox__arrow--previous" type="button" aria-label="Imagen anterior"><span aria-hidden="true">‹</span></button>
                <img class="walena-lightbox__image" alt="">
                <button class="walena-lightbox__arrow walena-lightbox__arrow--next" type="button" aria-label="Imagen siguiente"><span aria-hidden="true">›</span></button>
                <p class="walena-lightbox__caption" aria-live="polite"></p>
            </div>
            <div class="walena-lightbox__thumbnails" role="listbox" aria-label="Otras imágenes"></div>
        </div>
        <button class="walena-lightbox__close" type="button" aria-label="Cerrar galería"><span aria-hidden="true">×</span></button>
    `;
    document.body.appendChild(lightbox);

    const mainImage = lightbox.querySelector('.walena-lightbox__image');
    const caption = lightbox.querySelector('.walena-lightbox__caption');
    const counter = lightbox.querySelector('.walena-lightbox__counter');
    const thumbnails = lightbox.querySelector('.walena-lightbox__thumbnails');
    const closeButton = lightbox.querySelector('.walena-lightbox__close');
    const previousButton = lightbox.querySelector('.walena-lightbox__arrow--previous');
    const nextButton = lightbox.querySelector('.walena-lightbox__arrow--next');

    let activeCards = [];
    let activeImages = [];
    let activeIndex = 0;
    let returnFocusTo = null;
    let lastWheelMove = 0;

    const titleOf = (card) => {
        const image = card.querySelector('img');
        const heading = card.querySelector('h2, h3');
        return heading?.textContent.trim() || image?.alt || 'Imagen de Hotel Walena';
    };

    const showImage = (index) => {
        activeIndex = (index + activeImages.length) % activeImages.length;
        const entry = activeImages[activeIndex];

        mainImage.src = entry.src;
        mainImage.alt = entry.alt || entry.title;
        caption.textContent = entry.title;
        counter.textContent = `${activeIndex + 1} / ${activeImages.length}`;

        mainImage.classList.remove('is-changing');
        void mainImage.offsetWidth;
        mainImage.classList.add('is-changing');

        thumbnails.querySelectorAll('.walena-lightbox__thumbnail').forEach((button, buttonIndex) => {
            const selected = buttonIndex === activeIndex;
            button.setAttribute('aria-current', selected ? 'true' : 'false');
            if (selected) button.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        });
    };

    const openGallery = (card) => {
        const group = card.dataset.lightboxGroup;
        activeCards = cards.filter((item) => item.dataset.lightboxGroup === group);
        activeImages = activeCards.flatMap((item) => {
            const title = titleOf(item);
            const primary = item.querySelector('img');
            const images = primary ? [{ src: primary.currentSrc || primary.src, alt: primary.alt, title }] : [];
            item.querySelectorAll('[data-gallery-image]').forEach((extra) => {
                images.push({ src: extra.dataset.galleryImage, alt: extra.dataset.galleryAlt || title, title });
            });
            return images;
        });
        activeIndex = 0;
        returnFocusTo = card;
        thumbnails.replaceChildren();

        activeImages.forEach((item, index) => {
            const button = document.createElement('button');
            const thumbnail = document.createElement('img');
            button.type = 'button';
            button.className = 'walena-lightbox__thumbnail';
            button.setAttribute('role', 'option');
            button.setAttribute('aria-label', `Ver imagen ${index + 1} de ${item.title}`);
            thumbnail.src = item.src;
            thumbnail.alt = '';
            button.appendChild(thumbnail);
            button.addEventListener('click', () => showImage(index));
            thumbnails.appendChild(button);
        });

        showImage(activeIndex);
        lightbox.classList.add('is-open');
        lightbox.setAttribute('aria-hidden', 'false');
        document.body.classList.add('walena-lightbox-open');
        closeButton.focus();
    };

    const closeGallery = () => {
        lightbox.classList.remove('is-open');
        lightbox.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('walena-lightbox-open');
        if (returnFocusTo) returnFocusTo.focus();
    };

    cards.forEach((card) => {
        card.tabIndex = 0;
        card.setAttribute('role', 'button');
        card.setAttribute('aria-haspopup', 'dialog');
        card.setAttribute('aria-label', `Ampliar ${titleOf(card)}`);
        card.addEventListener('click', () => openGallery(card));
        card.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                openGallery(card);
            }
        });
    });

    closeButton.addEventListener('click', closeGallery);
    previousButton.addEventListener('click', () => showImage(activeIndex - 1));
    nextButton.addEventListener('click', () => showImage(activeIndex + 1));
    lightbox.addEventListener('click', (event) => {
        if (event.target === lightbox) closeGallery();
    });

    lightbox.addEventListener('wheel', (event) => {
        if (!lightbox.classList.contains('is-open') || Math.abs(event.deltaY) < 18) return;
        if (event.target.closest('.walena-lightbox__thumbnails')) return;
        event.preventDefault();
        const now = Date.now();
        if (now - lastWheelMove < 500) return;
        lastWheelMove = now;
        showImage(activeIndex + (event.deltaY > 0 ? 1 : -1));
    }, { passive: false });

    document.addEventListener('keydown', (event) => {
        if (!lightbox.classList.contains('is-open')) return;
        if (event.key === 'Escape') closeGallery();
        if (event.key === 'ArrowRight') showImage(activeIndex + 1);
        if (event.key === 'ArrowLeft') showImage(activeIndex - 1);
    });
})();
