'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const [pagePath, rpcPath, measured] = process.argv.slice(2);
const rpcFragment = fs.readFileSync(rpcPath, 'utf8');

function temperatureRPC(value, exitCode = 0, open = true) {
    const calls = [];
    const result = vm.runInNewContext('const methods = {\n' + rpcFragment +
        '\n}; methods.getTempInfo.call({args: {command: "unexpected"}});', {
        trim: text => text.trim(),
        popen: (...args) => {
            calls.push(args);
            return open ? {read: () => value, close: () => exitCode} : null;
        }
    });
    assert.deepEqual(calls, [['/sbin/tempinfo 2>/dev/null', 'r']]);
    return result.tempinfo;
}

assert.equal(temperatureRPC(measured + '\n'), measured);
assert.equal(temperatureRPC('No temperature info'), '');
assert.equal(temperatureRPC(null), '');
assert.equal(temperatureRPC('partial value', 1), '');
assert.equal(temperatureRPC('partial value', null), '');
assert.equal(temperatureRPC('', 0, false), '');

async function renderSystem(value, fail = false) {
    const declarations = [];
    const responses = {
        board: {hostname: 'ponwrt', model: 'ZNXT ZN504XG-D',
                system: 'ARMv8 Processor rev 4', kernel: '6.18.52',
                release: {target: 'airoha/an7581', description: 'PonWrt'}},
        info: {},
        getVersion: {branch: 'LuCI', revision: 'test'},
        getUnixtime: {result: 0},
        getTempInfo: {tempinfo: value},
    };
    const scope = {
        baseclass: {extend: x => x},
        rpc: {declare: declaration => {
            declarations.push(declaration);
            return () => {
                if (fail && declaration.method === 'getTempInfo')
                    return Promise.reject(new Error('sensor/RPC unavailable'));
                const result = responses[declaration.method];
                return Promise.resolve(declaration.expect ?
                    (result[Object.keys(declaration.expect)[0]] ??
                     Object.values(declaration.expect)[0]) : result);
            };
        }},
        uci: {load: () => Promise.resolve({}), get: () => null},
        _: x => x,
        L: {isObject: x => x && typeof x === 'object',
            resolveDefault: (promise, fallback) => Promise.resolve(promise).catch(() => fallback)},
        E: (tag, attributes, children = []) => ({
            tag, attributes, children,
            appendChild(child) {this.children.push(child);}
        })
    };
    const page = vm.runInNewContext('(function(){\n' + fs.readFileSync(pagePath, 'utf8') +
        '\n})()', scope);
    const table = page.render(await page.load());
    const rows = Object.fromEntries(table.children.map(row =>
        [row.children[0].children[0], row.children[1].children[0]]));
    assert.equal(rows.Architecture, 'ARMv8 Processor rev 4');
    assert.equal(rows['Target Platform'], 'airoha/an7581');
    assert.equal(rows.Model, 'ZNXT ZN504XG-D');
    assert.ok(declarations.some(d => d.object === 'luci' && d.method === 'getTempInfo'));
    return rows.Temperature;
}

(async () => {
    assert.equal(await renderSystem(temperatureRPC(measured)), measured);
    assert.equal(await renderSystem(''), 'Unavailable');
    assert.equal(await renderSystem('', true), 'Unavailable');
    console.log('Temperature RPC and status rendering passed: ' + measured);
})().catch(error => {console.error(error); process.exitCode = 1;});
