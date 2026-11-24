// Platform entry for the shared components in ./components/.
import * as components from './components/index.js';
window.RunTeamsUIComponents = components;
window.dispatchEvent(new Event('runteams-ui-ready'));
