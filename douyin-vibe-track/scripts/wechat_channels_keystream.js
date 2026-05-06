#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const decodeKey = process.argv[2];
const outputFormat = process.argv[3] || "hex";

if (!decodeKey) {
  console.error("Usage: node wechat_channels_keystream.js <decode_key> [hex|base64]");
  process.exit(2);
}

const vendorDir = path.resolve(__dirname, "vendor", "wechat_channels");
const wasmPath = path.join(vendorDir, "wasm_video_decode.wasm");
const jsPath = path.join(vendorDir, "wasm_video_decode.js");

if (!fs.existsSync(wasmPath) || !fs.existsSync(jsPath)) {
  console.error("Missing vendored WeChat Channels WASM assets.");
  process.exit(2);
}

let keystream = null;
let completed = false;
let timeoutId = null;

global.VTS_WASM_URL = wasmPath;
global.self = { location: { href: `file://${jsPath}` } };
global.document = { title: "" };
global.XMLHttpRequest = function XMLHttpRequest() {
  throw new Error("XMLHttpRequest should not be called in local keystream generation");
};
global.fetch = async (url) => {
  const filepath = String(url);
  const data = fs.readFileSync(filepath);
  return new Response(data, {
    headers: {
      "Content-Type": "application/wasm",
    },
  });
};
global.Module = {
  printErr: (...args) => {
    const message = args.join(" ");
    if (!message.includes("falling back to ArrayBuffer instantiation") && !message.includes("wasm streaming compile failed")) {
      console.error(message);
    }
  },
  onRuntimeInitialized() {
    try {
      const decryptor = new Module.WxIsaac64(String(decodeKey));
      decryptor.generate(131072);
      decryptor.delete();
      if (!keystream) {
        throw new Error("keystream callback did not run");
      }
      if (outputFormat === "base64") {
        process.stdout.write(Buffer.from(keystream).toString("base64"), () => {
          completed = true;
          if (timeoutId) {
            clearTimeout(timeoutId);
          }
        });
      } else {
        process.stdout.write(Buffer.from(keystream).toString("hex"), () => {
          completed = true;
          if (timeoutId) {
            clearTimeout(timeoutId);
          }
        });
      }
    } catch (error) {
      console.error(error instanceof Error ? error.message : String(error));
      process.exitCode = 1;
    }
  },
};
global.wasm_isaac_generate = (ptr, size) => {
  keystream = new Uint8Array(size);
  const wasmArray = new Uint8Array(Module.HEAPU8.buffer, ptr, size);
  keystream.set(Array.from(wasmArray).reverse());
};

vm.runInThisContext(fs.readFileSync(jsPath, "utf8"), { filename: jsPath });

process.stdout.on("error", (error) => {
  if (error && error.code === "EPIPE") {
    process.exit(0);
  }
  throw error;
});

timeoutId = setTimeout(() => {
  if (!completed) {
    console.error("Timed out waiting for WeChat Channels WASM runtime.");
    process.exitCode = 1;
    process.exit(1);
  }
}, 30000);
