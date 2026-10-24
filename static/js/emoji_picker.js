(function () {
    const closePicker = (picker) => {
        picker.hidden = true;
        const toggle = picker.parentElement.querySelector('[data-emoji-picker-toggle]');
        toggle?.setAttribute('aria-expanded', 'false');
    };

    document.addEventListener('click', (event) => {
        const toggle = event.target.closest('[data-emoji-picker-toggle]');
        if (toggle) {
            const picker = toggle.parentElement.querySelector('[data-emoji-picker]');
            if (!picker) return;
            document.querySelectorAll('[data-emoji-picker]:not([hidden])').forEach((openPicker) => {
                if (openPicker !== picker) closePicker(openPicker);
            });
            picker.hidden = !picker.hidden;
            toggle.setAttribute('aria-expanded', String(!picker.hidden));
            return;
        }

        const choice = event.target.closest('[data-emoji]');
        if (choice) {
            const picker = choice.closest('[data-emoji-picker]');
            const form = choice.closest('form');
            const textarea = form?.querySelector('textarea[name="body"]');
            if (!picker || !textarea) return;
            const start = textarea.selectionStart ?? textarea.value.length;
            const end = textarea.selectionEnd ?? start;
            const emoji = choice.dataset.emoji;
            textarea.value = textarea.value.slice(0, start) + emoji + textarea.value.slice(end);
            textarea.focus();
            const cursor = start + emoji.length;
            textarea.setSelectionRange(cursor, cursor);
            closePicker(picker);
            return;
        }

        if (!event.target.closest('[data-emoji-picker]')) {
            document.querySelectorAll('[data-emoji-picker]:not([hidden])').forEach(closePicker);
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;
        document.querySelectorAll('[data-emoji-picker]:not([hidden])').forEach(closePicker);
    });
})();
