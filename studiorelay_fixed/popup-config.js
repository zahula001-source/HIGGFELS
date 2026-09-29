// StudioRelay license presentation flag. Internal API name is preserved for compatibility.
window.CHANNA_EXTENSION_FLAGS = Object.freeze({
    licenseFrontPageEnabled: true
});

if (!window.CHANNA_EXTENSION_FLAGS.licenseFrontPageEnabled) {
    document.documentElement.classList.add('license-front-page-disabled');
}
