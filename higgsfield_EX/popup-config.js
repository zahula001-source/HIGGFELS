// StudioRelay license presentation flag.
// Set licenseFrontPageEnabled to false so the extension opens directly into the main unlocked UI.
window.CHANNA_EXTENSION_FLAGS = Object.freeze({
    licenseFrontPageEnabled: false
});

if (!window.CHANNA_EXTENSION_FLAGS.licenseFrontPageEnabled) {
    document.documentElement.classList.add('license-front-page-disabled');
}
