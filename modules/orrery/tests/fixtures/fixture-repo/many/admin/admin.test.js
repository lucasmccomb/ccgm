const m = require('./index')
if (m.feature !== 'admin') throw new Error('fixture self-check')
