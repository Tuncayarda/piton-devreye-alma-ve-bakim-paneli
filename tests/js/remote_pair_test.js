// The two ways into a remote admin session, and the dialog that offers both.
//
// There used to be a third — eight characters read down a telephone into two
// boxes of four, with a button swapping them for the square — and most of
// this file was about pasting a code into whichever box happened to have the
// cursor. That way in is gone (see app.js). What is asserted now is what
// replaced it: two columns, each named by a heading that follows the face
// inside it, and the square's own arithmetic underneath.
//
// The dialog is lifted out of `app.js` and run against stand-in `el`, `fill`
// and `dialog` helpers. Importing app.js itself would start the whole
// application — it wires the top bar and begins polling at module load — and
// none of that is what these assertions are about.
import assert from "node:assert/strict";

const SOURCE = new URL("../../static/js/app.js", import.meta.url);
const text = await Deno.readTextFile(SOURCE);

// The block between the two markers is the dialog and its account column and
// nothing else. Read from the file rather than copied here: a copy would
// keep passing after the original changed, which is the one thing this must
// not do.
const FROM = "function askForRemoteSession() {";
const TO = "// ─────────────────────────────────────────────── the square ";
const start = text.indexOf(FROM);
const end = text.indexOf(TO);
assert.ok(start !== -1 && end > start,
  "the remote dialog was not found in app.js — did its markers move?");

const SHIM = `
// The square is its own story (it talks to the service); here it is a pair
// of names so that opening the dialog works at all.
let SQUARE = null;
const startPairing = (node) => { SQUARE = node; };
const stopPairing = () => { SQUARE = null; };

let FOCUSED = null;
const field = (props) => {
  const self = {
    tagName: "INPUT", props, children: [], value: props.value || "",
    focus() { FOCUSED = self; },
  };
  return self;
};
const el = (tag, props = {}, children = []) => (
  tag === "input" ? field(props)
    : { tagName: String(tag).toUpperCase(), props, children,
        textContent: props.text,
        get disabled() { return !!props.disabled; },
        set disabled(v) { props.disabled = v; },
        click() { props.onclick && props.onclick(); } }
);
const fill = (node, children) => {
  node.children = children.filter(Boolean);
  return node;
};
const t = (key) => key;
let SHOWN = null;
const dialog = { show: (options) => { SHOWN = options; }, close() {} };
// The service, and everything the panel does with an answer from it. None of
// the three is what this file is about; a sign-in that resolves is enough to
// let the form run to the end.
const api = {
  remoteSignin: () => Promise.resolve({ remote: {} }),
  remoteSignup: () => Promise.resolve({}),
};
const patch = () => {};
const applyEdition = () => {};
const showSuccess = () => {};
`;

const EXPORTS = `
// The dialog is two columns — an account on one side, the square on the
// other — so nothing here counts to a node. Everything is looked up by the
// class it is drawn with, which is the name the stylesheet uses too: a line
// added above a column, or another way in beside it, must not silently point
// these tests at the wrong box.
const findBy = (node, want) => {
  if (!node || typeof node !== "object") return null;
  // BY TOKEN, not by the whole attribute: a node drawn with
  // "remote-way remote-pair" carries the name being asked for, and an exact
  // match would quietly answer null for every element that has more than
  // one class.
  //
  // SPLIT ON A SPACE, NOT ON \\s. This helper lives inside a template
  // literal, and a template literal eats the backslash: /\\s+/ written here
  // reaches the module as /s+/ and splits class names on the letter s.
  // "remote-account" survived that and "remote-square" did not, which is a
  // failure that looks like a missing element rather than a broken regex.
  if (node.props
      && String(node.props.class || "").split(" ").includes(want)) {
    return node;
  }
  for (const child of node.children || []) {
    const found = findBy(child, want);
    if (found) return found;
  }
  return null;
};

const all = (node, want, into = []) => {
  if (!node || typeof node !== "object") return into;
  if (node.props
      && String(node.props.class || "").split(" ").includes(want)) {
    into.push(node);
  }
  for (const child of node.children || []) all(child, want, into);
  return into;
};

const head = (side) => {
  const found = findBy(side, "remote-way-head");
  return found && found.props.text;
};

export function box() {
  askForRemoteSession();
  const account = findBy(SHOWN.content, "remote-account");
  const pair = findBy(SHOWN.content, "remote-pair");
  return {
    ways: SHOWN.content,
    account, pair,
    heads: () => [head(account), head(pair)],
    fields: () => all(account, "field"),
    labels: () => all(account, "label").map((node) => node.props.text),
    submit: () => findBy(account, "remote-submit"),
    link: () => findBy(account, "btn-link"),
    focused: () => FOCUSED,
    square: () => SQUARE,
    plate: findBy(pair, "remote-square"),
    close: () => SHOWN.onClose && SHOWN.onClose(),
    gone: (name) => findBy(SHOWN.content, name),
  };
}
export { PAIR_QUIET, PAIR_SIDE, squareBox };
`;

// The square's own arithmetic, lifted out the same way. It has no
// dependencies at all — it is a number in and a number out — so it is
// appended to the module rather than given a file of its own.
const SIZE_FROM = "const PAIR_SIDE = ";
const SIZE_TO = "function stopPairing()";
const sizeStart = text.indexOf(SIZE_FROM);
const sizeEnd = text.indexOf(SIZE_TO);
assert.ok(sizeStart !== -1 && sizeEnd > sizeStart,
  "the square's sizing was not found in app.js — did its markers move?");

const module = await import(
  "data:text/javascript;charset=utf-8," +
  encodeURIComponent(
    SHIM + text.slice(start, end) + text.slice(sizeStart, sizeEnd) + EXPORTS,
  )
);

// ── two ways in, side by side ───────────────────────────────────────────
Deno.test("both ways in open together, and both are named", () => {
  // The columns are drawn alike on purpose, so the heading is the only thing
  // telling them apart: a column that lost its heading would look exactly
  // like the other one and say nothing about what it wants.
  const ui = module.box();
  assert.ok(ui.account, "the account column is drawn");
  assert.ok(ui.pair, "the square's column is drawn");
  assert.deepEqual(ui.heads(), ["remote.wayAccount", "remote.wayQr"]);
});

Deno.test("signing in asks for two things and offers one button", () => {
  const ui = module.box();
  assert.deepEqual(ui.labels(), ["remote.email", "remote.password"]);
  assert.equal(ui.submit().props.text, "remote.signIn");
  assert.equal(ui.link().props.text, "remote.signUp");
  assert.equal(ui.focused(), ui.fields()[0], "the caret starts in the first");
});

Deno.test("the heading follows the face inside the column", () => {
  // The whole column is refilled on a swap, heading and all. A column headed
  // "sign in with an account" over a four-field "create an account" form is
  // a heading that has stopped describing what is under it.
  const ui = module.box();
  ui.link().click();
  assert.deepEqual(ui.heads(), ["remote.signUp", "remote.wayQr"]);
  assert.deepEqual(ui.labels(), [
    "remote.name", "remote.email", "remote.password", "remote.passwordAgain",
  ]);
  assert.equal(ui.submit().props.text, "remote.signUp");

  ui.link().click();                                  // and back again
  assert.deepEqual(ui.heads(), ["remote.wayAccount", "remote.wayQr"]);
  assert.deepEqual(ui.labels(), ["remote.email", "remote.password"]);
});

Deno.test("the address typed in comes along to the other face", () => {
  // Somebody who filled the address in, was told there is no such account
  // and pressed "create one" must not be asked for it a second time.
  const ui = module.box();
  ui.fields()[0].value = "engineer@example.test";
  ui.link().click();
  assert.equal(ui.fields()[1].props.value, "engineer@example.test");
});

Deno.test("the square is asked for on opening and given up on closing", () => {
  // Both halves of the dialog are live at once: the operator either points a
  // phone at the square or signs in as themselves, and whichever they do the
  // other must not be left running. Closing is the only place that knows the
  // square has stopped being looked at.
  const ui = module.box();
  assert.equal(ui.square(), ui.plate, "the square is the plate in its column");
  ui.close();
  assert.equal(ui.square(), null, "closing should give the pairing back");
});

Deno.test("no code box was left behind", () => {
  // The way in that asked the operator to transcribe eight characters is
  // gone, and so is the button that swapped it for the square. If either
  // comes back it comes back on purpose, with its own tests.
  const ui = module.box();
  for (const name of ["remote-code-row", "remote-code-pane", "remote-swap"]) {
    assert.equal(ui.gone(name), null, name);
  }
});

// ── how big the square is drawn ─────────────────────────────────────────
Deno.test("the square is sized to whole pixels per module", () => {
  // A module that is 7.3 pixels wide comes out alternating seven and eight,
  // because the drawing asks for crisp edges rather than a blur. Every
  // square the same size is what a decoder starts from, so the scale is
  // rounded DOWN to a whole number and the picture gives up the remainder.
  //
  // WHAT MUST FIT THE PLATE IS WHAT IS SEEN, not the whole picture. The
  // scale used to be worked out from every module the service drew, margin
  // included, and then some of that margin was cropped away — so the code
  // was sized against white nobody ever looked at and came out a pixel a
  // module smaller than the plate could carry. The picture is now larger
  // than the plate on purpose: the part hanging outside it is the margin
  // being cropped.
  for (const modules of [21, 25, 29, 33, 37, 41, 45, 49, 53, 57, 65, 177]) {
    const { side, shown } = module.squareBox(modules, 4);
    assert.equal(side % modules, 0, `${modules} modules -> ${side}px`);
    assert.ok(shown <= module.PAIR_SIDE, `${modules} modules must not grow`);
    assert.ok(side >= modules, `${modules} modules must stay visible`);
  }
});

Deno.test("the plate is filled by the code, not by its margin", () => {
  // The complaint this arithmetic answers: a small drawing floating in the
  // middle of a white card. The code used to be scaled against every module
  // the service drew, margin included, and then part of that margin was
  // cropped — so it was sized against white nobody ever saw.
  //
  // What is asserted is that the scale is the LARGEST whole number of pixels
  // per module that still leaves the quiet zone inside the plate: one pixel
  // more and the code plus its clear border would not fit. Everything else —
  // how little white is left, how big the code comes out — follows from it.
  for (const modules of [29, 37, 41, 49]) {
    for (const quiet of [0, 2, 4, 8]) {
      const { side, shown } = module.squareBox(modules, quiet);
      const scale = side / modules;
      const kept = Math.min(quiet, module.PAIR_QUIET);
      // The code, the margin the picture kept, and the margin the plate has
      // to supply because the picture did not carry it.
      const box = shown / scale + (module.PAIR_QUIET - kept) * 2;
      assert.ok(box * scale <= module.PAIR_SIDE,
        `${modules}/${quiet}: ${box * scale}px does not fit ${module.PAIR_SIDE}`);
      assert.ok(scale === 1 || box * (scale + 1) > module.PAIR_SIDE,
        `${modules}/${quiet}: ${scale + 1}px a module would still have fitted`);
    }
  }
});

Deno.test("the crop takes margin and never takes code", () => {
  // What is cropped is white the service measured and reported. Cropping
  // past it would eat the code, and no arithmetic here may arrive there.
  for (const modules of [29, 37, 41, 49]) {
    for (const quiet of [0, 1, 2, 3, 4, 8]) {
      const { side, shown, offset } = module.squareBox(modules, quiet);
      const scale = side / modules;
      const cropped = (side - shown) / 2;
      assert.equal(cropped, -offset, "the picture moves by what is hidden");
      assert.ok(cropped >= 0, "the window never grows past the picture");
      assert.ok(cropped <= quiet * scale,
        `${quiet} modules of margin, ${cropped / scale} cropped`);
      const left = quiet - cropped / scale;
      assert.ok(left >= Math.min(quiet, module.PAIR_QUIET),
        `${quiet} modules of margin left ${left}`);
    }
  }
});

Deno.test("a picture that arrived without its measurements still draws", () => {
  for (const nothing of [undefined, null, 0, -4, "wide", NaN]) {
    const { side, shown, offset } = module.squareBox(nothing, 4);
    assert.equal(side, module.PAIR_SIDE);
    assert.equal(shown, module.PAIR_SIDE);
    assert.equal(offset, 0);
  }
});
