const m = require('./index')
if (m.feature !== 'feature-flags') throw new Error('fixture self-check')
