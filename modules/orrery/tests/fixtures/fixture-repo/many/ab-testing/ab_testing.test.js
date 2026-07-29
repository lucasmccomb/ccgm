const m = require('./index')
if (m.feature !== 'ab-testing') throw new Error('fixture self-check')
