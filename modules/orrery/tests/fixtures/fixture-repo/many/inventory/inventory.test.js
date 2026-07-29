const m = require('./index')
if (m.feature !== 'inventory') throw new Error('fixture self-check')
