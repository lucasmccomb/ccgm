const m = require('./index')
if (m.feature !== 'auth') throw new Error('fixture self-check')
