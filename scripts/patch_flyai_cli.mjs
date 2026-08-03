import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const PACKAGE_PATH = join(ROOT, "node_modules", "@fly-ai", "flyai-cli", "package.json");
const BUNDLE_PATH = join(ROOT, "node_modules", "@fly-ai", "flyai-cli", "dist", "flyai-bundle.cjs");
const EXPECTED_VERSION = "1.0.16";
const ORIGINAL_SHA256 = "194a66eb84094f3d8ee20fac0a2d6cae10a405cd59ac100b7e7880ebc97297da";
const PATCHED_SHA256 = "249791ae4274cdec3bbb9babb2788ceada291f94623f7c16d3901d16c8e41f58";

const REPLACEMENTS = [
  [
    "let h=await g(d,f,'search_flight',c);if(h!=null){let i=_(h);console['log'](JSON['stringify'](i)),process['exit'](0x0);}process['exit'](0x1);}console['log'](JSON['stringify']({'tool':'search_flight','arguments':c})),/^(1|true|yes)$/i['test'](process.env.FLYAI_JSON??'')||console['error']('SYSTEM_ERROR'),process['exit'](0x0);",
    "let h=await g(d,f,'search_flight',c);if(h!=null){let i=_(h);console['log'](JSON['stringify'](i)),process['exitCode']=0x0;return;}process['exit'](0x1);}console['log'](JSON['stringify']({'tool':'search_flight','arguments':c})),/^(1|true|yes)$/i['test'](process.env.FLYAI_JSON??'')||console['error']('SYSTEM_ERROR'),process['exitCode']=0x0;return;",
  ],
  [
    "let h=await g(d,f,'search_domestic_train',c);if(h!=null){let i=_(h);console['log'](JSON['stringify'](i)),process['exit'](0x0);}process['exit'](0x1);}console['log'](JSON['stringify']({'tool':'search_train','arguments':c})),/^(1|true|yes)$/i['test'](process.env.FLYAI_JSON??'')||console['error']('SYSTEM_ERROR'),process['exit'](0x0);",
    "let h=await g(d,f,'search_domestic_train',c);if(h!=null){let i=_(h);console['log'](JSON['stringify'](i)),process['exitCode']=0x0;return;}process['exit'](0x1);}console['log'](JSON['stringify']({'tool':'search_train','arguments':c})),/^(1|true|yes)$/i['test'](process.env.FLYAI_JSON??'')||console['error']('SYSTEM_ERROR'),process['exitCode']=0x0;return;",
  ],
];

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function fail(message) {
  throw new Error(`FlyAI patch gate failed: ${message}`);
}

const packageJson = JSON.parse(readFileSync(PACKAGE_PATH, "utf8"));
if (packageJson.version !== EXPECTED_VERSION) {
  fail(`expected @fly-ai/flyai-cli@${EXPECTED_VERSION}, found ${packageJson.version}`);
}

const originalBundle = readFileSync(BUNDLE_PATH);
const originalHash = sha256(originalBundle);
if (originalHash === PATCHED_SHA256) {
  const patchedText = originalBundle.toString("utf8");
  if (REPLACEMENTS.some(([before]) => patchedText.includes(before))) {
    fail("patched hash still contains an unpatched ticket action");
  }
  console.log(`FlyAI CLI patch verified: ${PATCHED_SHA256}`);
  process.exitCode = 0;
} else {
  if (process.argv.includes("--check")) {
    fail(`expected patched hash ${PATCHED_SHA256}, found ${originalHash}`);
  }
  if (originalHash !== ORIGINAL_SHA256) {
    fail(`expected official bundle hash ${ORIGINAL_SHA256}, found ${originalHash}`);
  }
  let patchedText = originalBundle.toString("utf8");
  for (const [before, after] of REPLACEMENTS) {
    const first = patchedText.indexOf(before);
    if (first < 0 || patchedText.indexOf(before, first + before.length) >= 0) {
      fail("ticket action target must occur exactly once");
    }
    patchedText = patchedText.replace(before, after);
  }
  const patchedBundle = Buffer.from(patchedText, "utf8");
  const patchedHash = sha256(patchedBundle);
  if (patchedHash !== PATCHED_SHA256) {
    fail(`patched hash mismatch: expected ${PATCHED_SHA256}, found ${patchedHash}`);
  }
  writeFileSync(BUNDLE_PATH, patchedBundle);
  console.log(`FlyAI CLI patch applied: ${ORIGINAL_SHA256} -> ${PATCHED_SHA256}`);
}
