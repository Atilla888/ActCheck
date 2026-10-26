const assert = require('node:assert/strict')
const fs = require('node:fs')
const ts = require('typescript')
const messages = require('../src/lib/i18n/messages.json')
const tokens = value => [...value.matchAll(/\{(\w+)\}/g)].map(match => match[1]).sort()
for (const [key, translations] of Object.entries(messages)) {
  for (const locale of ['ru', 'kk']) {
    assert.ok(translations[locale]?.trim(), `Missing ${locale}: ${key}`)
    assert.deepEqual(tokens(translations[locale]), tokens(key), `Interpolation mismatch: ${locale}: ${key}`)
  }
}
const files = ['src/App.tsx','src/components/ui/dialog.tsx',...fs.readdirSync('src/features/inspection').filter(file=>file.endsWith('.tsx')).map(file=>'src/features/inspection/'+file)]
let calls=0
for(const file of files) {
  const source=ts.createSourceFile(file,fs.readFileSync(file,'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX)
  function visit(node){
    if(ts.isCallExpression(node)&&node.expression.getText(source)==='t'&&ts.isStringLiteral(node.arguments[0])) {
      const key=node.arguments[0].text
      assert.ok(messages[key],`Untranslated key in ${file}: ${key}`)
      calls++
    }
    ts.forEachChild(node,visit)
  }
  visit(source)
}
// Fixture display fields are dynamically translated; user input never is.
const source=ts.createSourceFile('data.ts',fs.readFileSync('src/features/inspection/data.ts','utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TS)
function visit(node) {
  if(ts.isPropertyAssignment(node)&&['name','detail','explanation','question','location','notes','review','matched','unverified'].includes(node.name.getText(source))&&ts.isStringLiteral(node.initializer)&&node.initializer.text) {
    assert.ok(messages[node.initializer.text],`Untranslated fixture: ${node.initializer.text}`)
  }
  ts.forEachChild(node,visit)
}
visit(source)
console.log(`PASS: ${Object.keys(messages).length} messages, RU/KK placeholder parity, ${calls} static calls, and fixture translations.`)
