import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/game.rs", import.meta.url), "utf8");
const fixtureDir = new URL("../fixtures/", import.meta.url);
const checkFixture = JSON.parse(readFileSync(new URL("check.json", fixtureDir), "utf8"));
const wrongOriginFixture = JSON.parse(readFileSync(new URL("wrong-origin.json", fixtureDir), "utf8"));
const statusSource = source.match(/pub const STATUS:&str = r#"([\s\S]*?)"#;/)?.[1];
const travelTemplate = source.match(/let expression=format!\(r#"([\s\S]*?)"#,lake\);/)?.[1];
const pocketSource = source.match(/let pocket=r#"([\s\S]*?)"#;/)?.[1];
const breadSource = source.match(/let bread=r#"([\s\S]*?)"#;/)?.[1];
assert.ok(statusSource, "STATUS must be extracted from game.rs");
assert.ok(travelTemplate, "travel selector must be extracted from game.rs");
assert.ok(pocketSource, "Pocket selector must be extracted from game.rs");
assert.ok(breadSource, "Bread selector must be extracted from game.rs");

const failures = [];
function check(name, fn) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    failures.push(`${name}: ${error.message}`);
    console.error(`FAIL ${name}: ${error.message}`);
  }
}

function statusFor({ energyText = "70 / 80", xpText = "1,234 XP", toast = "", energyPresent = true } = {}) {
  const window = {};
  const document = {
    documentElement: {},
    querySelector(selector) {
      if (selector === "div.info > div.number" && energyPresent) return { innerText: energyText };
      if (selector === ".message-bar") return { innerText: toast };
      if (selector === ".remaining-xp") return xpText === null ? null : { innerText: xpText };
      return null;
    },
    querySelectorAll(selector) { return selector === ".modal-body" ? [] : []; },
  };
  class MutationObserver { observe() {} }
  const run = new Function("window", "document", "location", "innerWidth", "innerHeight", "devicePixelRatio", "MutationObserver", "getComputedStyle", `return ${statusSource};`);
  return run(window, document, { href: "https://nomstead.com/qn" }, 1280, 720, 1, MutationObserver, () => ({ visibility: "visible" }));
}

check("STATUS executes the source expression and parses common energy forms", () => {
  assert.equal(statusFor({ energyText: "70 / 80" }).energy, 70);
  assert.equal(statusFor({ energyText: "0/80" }).energy, 0);
  assert.equal(statusFor({ energyText: "80 / 80" }).energy, 80);
  assert.equal(statusFor({ energyPresent: false }).energy, null);
  assert.equal(statusFor({ energyText: "not available" }).energy, null);
});

check("STATUS parses comma-formatted XP into a number", () => {
  assert.equal(statusFor({ xpText: "Remaining XP: 1,234" }).xp, 1234);
  assert.equal(statusFor({ xpText: "Remaining XP: 1234" }).xp, 1234);
  assert.equal(statusFor({ xpText: "no XP" }).xp, null);
});

check("status fixtures use numeric XP matching the Rust schema", () => {
  for (const fixture of [checkFixture, wrongOriginFixture]) {
    const status = fixture.find(entry => entry.method === "Runtime.evaluate").result.result.value;
    assert.equal(typeof status.xp, "number");
    assert.equal(status.xp, 123);
  }
});

function makeElement({ innerText = "", href = "", x = 10, y = 20 } = {}) {
  return {
    innerText, href,
    getAttribute: () => null,
    getClientRects: () => [{}],
    getBoundingClientRect: () => ({ x, y, width: 20, height: 10 }),
    scrollIntoView() {},
  };
}

function evaluateTravel(lake, names, linksByRow, modalCount = 1, active = true, visibleRows = []) {
  const rows = names.map((name, index) => ({
    getClientRects: () => visibleRows[index] === false ? [] : [{}],
    querySelectorAll(selector) {
      if (selector === ".info-meta > .description") return [makeElement({ innerText: name })];
      if (selector === 'a.btn[href^="/"]') return linksByRow[index] ?? [];
      return [];
    },
  }));
  const modal = makeElement();
  modal.querySelector = selector => selector === 'li.active[data-ui-tab="bookmarks"]' && active ? {} : null;
  modal.querySelectorAll = selector => selector === ".map ul.tiles > li.tile" ? rows : [];
  const expression = travelTemplate.replaceAll("{{", "{").replaceAll("}}", "}").replace("{}", String(lake));
  const run = new Function("document", "getComputedStyle", "location", `return ${expression};`);
  const result = run({ querySelectorAll: selector => selector === ".modal-body" ? Array(modalCount).fill(modal) : [] },
    () => ({ visibility: "visible" }), { origin: "https://nomstead.com" });
  return result;
}

const travelCases = [
  [1, "HO 1", "/travel/1"],
  [10, "HO 10", "/travel/10"],
  [11, "HO 11", "/travel/11"],
];
for (const [lake, name, path] of travelCases) {
  check(`travel selector chooses exact ${name} row`, () => {
    const result = evaluateTravel(lake, ["HO 1", "HO 10", "HO 11"],
      [[makeElement({ innerText: "Fast travel", href: "https://nomstead.com/travel/1" })],
       [makeElement({ innerText: "Fast travel", href: "https://nomstead.com/travel/10" })],
       [makeElement({ innerText: "Fast travel", href: "https://nomstead.com/travel/11" })]]);
    assert.equal(result.url, `https://nomstead.com${path}`);
  });
}

check("travel selector accepts case and whitespace but rejects HOs1", () => {
  const fast = makeElement({ innerText: "Fast travel", href: "https://nomstead.com/travel/1" });
  assert.equal(evaluateTravel(1, ["  hO   1  "], [[fast]]).url, "https://nomstead.com/travel/1");
  assert.match(evaluateTravel(1, ["HOs1"], [[fast]]).error, /missing or ambiguous/);
});

check("travel selector rejects duplicate rows and invalid link choices", () => {
  const fast = () => makeElement({ innerText: "Fast travel", href: "https://nomstead.com/travel/1" });
  const remove = makeElement({ innerText: "Remove", href: "https://nomstead.com/remove/1" });
  assert.equal(evaluateTravel(1, ["HO 1"], [[remove, fast()]]).url, "https://nomstead.com/travel/1");
  assert.match(evaluateTravel(1, ["HO 1", "HO 1"], [[fast()], [fast()]]).error, /missing or ambiguous/);
  assert.match(evaluateTravel(1, ["HO 1"], [[remove]]).error, /Fast travel link missing or ambiguous/);
  assert.match(evaluateTravel(1, ["HO 1"], [[fast(), fast()]]).error, /Fast travel link missing or ambiguous/);
  assert.match(evaluateTravel(1, ["HO 1"], [[makeElement({ innerText: "Fast travel", href: "https://evil.test/travel/1" })]]).error, /External destination/);
  assert.match(evaluateTravel(1, ["HO 1"], [[fast()]], 0).error, /Bookmarks modal missing or ambiguous/);
  assert.match(evaluateTravel(1, ["HO 1"], [[fast()]], 2).error, /Bookmarks modal missing or ambiguous/);
  assert.match(evaluateTravel(1, ["HO 1"], [[fast()]], 1, false).error, /Bookmarks modal missing or ambiguous/);
  assert.equal(evaluateTravel(1, ["HO 1", "HO 1"], [[fast()], [fast()]], 1, true, [false, true]).url,
    "https://nomstead.com/travel/1");
});

check("Pocket and Bread selectors accept exactly one visible labeled control", () => {
  const run = (expression, document) => new Function("document", "getComputedStyle", `return ${expression};`)(
    document, () => ({ visibility: "visible" }));
  const pocket = makeElement({ innerText: "Pocket", x: 30, y: 40 });
  const pocketDoc = controls => ({ querySelectorAll: selector => selector === "button,a,[role=button]" ? controls : [] });
  assert.equal(run(pocketSource, pocketDoc([pocket])).x, 40);
  assert.equal(run(pocketSource, pocketDoc([])), null);
  assert.equal(run(pocketSource, pocketDoc([pocket, pocket])), null);
  const bread = makeElement({ innerText: "  BREAD  ", x: 70, y: 80 });
  const modal = makeElement();
  modal.querySelectorAll = selector => selector === "button,a,[role=button]" ? [bread] : [];
  const breadDoc = modals => ({ querySelectorAll: selector => selector === ".modal-body" ? modals : [] });
  assert.equal(run(breadSource, breadDoc([modal])).x, 80);
  assert.equal(run(breadSource, breadDoc([])), null);
  assert.equal(run(breadSource, breadDoc([modal, modal])), null);
  modal.querySelectorAll = selector => selector === "button,a,[role=button]" ? [bread, bread] : [];
  assert.equal(run(breadSource, breadDoc([modal])), null);
});

if (failures.length) process.exitCode = 1;
