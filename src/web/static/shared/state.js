// State of the shown solution, shared by the viewer modules (one object: an ES module cannot reassign
// another module's `let`).
export const S = {
  view: null,        // the payload of the shown solution (GET /api/jobs/{id}/result or a saved run)
  colors: [],        // THREE.Color per item line, in view.lines order
  lineIndex: {},     // line id -> index in view.lines
  selected: null,    // index into view.containers, or null for the grid
  cur: null,         // the one container built in the 3D scene: {data, group, mesh, edges, pick, labels, order, count}
  step: 0,           // replay step: pieces shown
  playTimer: null,
  picked: null,      // index in replay order of the piece picked in the item table, or null
  itemRows: [],      // one row per piece of the selected container, in replay order
  drawerOpen: false,
  flagged: null,     // Set of item ids painted red (manual packing: the pieces the checker flags), or null
};
