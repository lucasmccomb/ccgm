const m = require('./index')
if (m.feature !== 'pricing') throw new Error('fixture self-check')
