// Live dashboard entry: every section in the registry and its tabs (tabs are optional).
// A section's commentary is its `export const commentary` (text above the chart, live numbers as {metric|format}).
import * as registry from './Sections/index.js';
import { mount } from './App.jsx';

const sections = registry.default;
const tabs = registry.tabs ?? [];
const commentary = Object.fromEntries(sections.filter((m) => m.commentary?.trim()).map((m) => [m.meta.id, m.commentary.trim()]));

mount({ sections, tabs, commentary });
