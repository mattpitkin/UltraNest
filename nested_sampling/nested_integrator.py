"""
Copyright: Johannes Buchner (C) 2013

Modular, Pythonic Implementation of Nested Sampling
"""

import numpy
from numpy import exp, log, log10, pi
import progressbar
from adaptive_progress import AdaptiveETA
from numpy import logaddexp

"""
Conservative (over)estimation of remainder integral (namely, the live points). 
The maximum likelihood is multiplied by the remaining volume.

:param sampler: Sampler
:param logwidth: current point weight
:param logVolremaining: current volume
:param logZ: current evidence

@return evidence contribution and uncertainty estimate
"""
def conservative_estimator(sampler, logwidth, logVolremaining, logZ):
	maxContribution = sampler.Lmax + logVolremaining
	logZup  = logaddexp(maxContribution, logZ)
	return maxContribution, logZup - logZ

"""
Conservative (over)estimation of remainder integral (namely, the live points).

The steps between the lowest and highest likelihood is integrated.
The choice where the step is done (at the lower, higher value or the mid point
gives a lower, upper and medium estimate. The medium estimate is returned.
The distance to the upper/lower (maximum) is used as a conservative estimate 
of the uncertainty.

:param sampler: Sampler
:param logwidth: current point weight
:param logVolremaining: current volume
:param logZ: current evidence

@return evidence contribution and uncertainty estimate
"""
def integrate_remainder(sampler, logwidth, logVolremaining, logZ, H, globalLmax):
	# logwidth remains the same now for each sample
	remainder = list(sampler.remainder())
	logV = logwidth
	L0 = remainder[-1][2]
	logLs = [Li - L0 for ui, xi, Li in remainder]
	Ls = numpy.exp([Li - L0 for ui, xi, Li in remainder])
	LsMax = Ls.copy()
	LsMax[-1] = numpy.exp(globalLmax - L0)
	
	"""
		      x---   4
		  x---       3
	      x---           2
	  x---               1
	  |   |   |   |   |


	  1 + 2 + 3 + 4
	  2 + 3 + 4 + 4
	  1 + 1 + 2 + 3
	"""
	# the positive edge is L2, L3, ... L-1, L-1
	# the average  edge is L1, L2, ... L-2, L-1
	# the negative edge is L1, L1, ... L-2, L-2
	#print globalLmax, ' '.join(['%.2f' % Li for Li in logLs])
	Lmax = LsMax[1:].sum() + LsMax[-1]
	#Lmax = Ls[1:].sum() + Ls[-1]
	Lmin = Ls[:-1].sum() + Ls[0]
	logLmid = log(Ls.sum()) + L0
	logZmid = logaddexp(logZ, logV + logLmid)
	logZup  = logaddexp(logZ, logV + log(Lmax) + L0)
	logZlo  = logaddexp(logZ, logV + log(Lmin) + L0)
	logZerr = logZup - logZlo
	
	# try bootstrapping for error estimation
	bs_logZmids = []
	for _ in range(20):
		i = numpy.random.randint(0, len(Ls), len(Ls))
		i.sort()
		bs_Ls = LsMax[i]
		Lmax = bs_Ls[1:].sum() + bs_Ls[-1]
		bs_Ls = Ls[i]
		Lmin = bs_Ls[:-1].sum() + bs_Ls[0]
		bs_logZmids.append(logaddexp(logZ, logV + log(Lmax.sum()) + L0))
		bs_logZmids.append(logaddexp(logZ, logV + log(Lmin.sum()) + L0))
	bs_logZerr = numpy.max(bs_logZmids) - numpy.min(bs_logZmids)
	
	for i in range(len(remainder)):
		ui, xi, Li = remainder[i]
		wi = logwidth + Li
		logZnew = logaddexp(logZ, wi)
		H = exp(wi - logZnew) * Li + exp(logZ - logZnew) * (H + logZ) - logZnew
		logZ = logZnew
	
	return logV + logLmid, logZerr, logZmid, logZerr + (H / sampler.nlive_points)**0.5, bs_logZerr + (H / sampler.nlive_points)**0.5

#integrate_remainder = conservative_estimator

"""
Performs the Nested Sampling integration by calling the *sampler* multiple times
until the *tolerance* is reached, or the maximum number of likelihood evaluations
is exceeded.

:param sampler: Sampler
:param tolerance: uncertainty in log Z to compute to
:param max_samples: maximum number of likelihood evaluations (None for no limit)

@return dictionary containing the keys

  logZ, logZerr: log evidence and uncertainty, 
  samples: all obtained samples,
  weights: posterior samples: 
  	list of prior coordinates, transformed coordinates, likelihood value 
  	and weight
  information: information H
  niterations: number of nested sampling iterations
"""
def nested_integrator(sampler, tolerance = 0.01, max_samples=None, 
	need_small_remainder=True, max_remainder=0.1,
	need_robust_remainder_error=False
):
	logVolremaining = 0
	logwidth = log(1 - exp(-1. / sampler.nlive_points))
	weights = [] #[-1e300, 1]]
	
	widgets = [progressbar.Counter('%f'),
		progressbar.Bar(), progressbar.Percentage(), AdaptiveETA()]
	pbar = progressbar.ProgressBar(widgets = widgets)
	
	i = 0
	ui, xi, Li = sampler.next()
	wi = logwidth + Li
	logZ = wi
	H = Li - logZ
	pbar.currval = i
	pbar.maxval = sampler.nlive_points
	pbar.start()
	while True:
		i = i + 1
		logwidth = log(1 - exp(-1. / sampler.nlive_points)) + logVolremaining
		logVolremaining -= 1. / sampler.nlive_points
		
		weights.append([ui, xi, Li, logwidth])
		
		logZerr = (H / sampler.nlive_points)**0.5
		
		#maxContribution = sampler.Lmax + logVolremaining
		#minContribution = Li + logVolremaining
		#midContribution = logaddexp(maxContribution, minContribution)
		#logZup  = logaddexp(maxContribution, logZ)
		#logZmid = logaddexp(midContribution, logZ)
		pbar.update(i)
		
		# expected number of iterations:
		i_final = -sampler.nlive_points * (-sampler.Lmax + log(exp(max(tolerance - logZerr, logZerr / 100.) + logZ) - exp(logZ)))
		pbar.maxval = min(max(i+1, i_final), i+100000)
		#logmaxContribution = logZup - logZ
		
		if i == 1 or (i > sampler.nlive_points and i % 10 == 1):
			remainderZ, remainderZerr, totalZ, totalZerr, totalZerr_bootstrapped = integrate_remainder(
				sampler, logwidth, logVolremaining, logZ, H, sampler.Lmax)
		
		if i > sampler.nlive_points:
			# tolerance
			total_error = totalZerr
			if max_samples is not None and int(max_samples) < int(sampler.ndraws):
				pbar.finish()
				print 'maximum number of samples reached'
				break
			if total_error < tolerance and (not need_small_remainder or remainderZ < totalZ + log(max_remainder)) and (not need_robust_remainder_error or totalZerr_bootstrapped < tolerance):
				pbar.finish()
				print 'tolerance on error reached: total=%.4f (BS: %.4f) stat=%.4f remainder=%.4f' % (total_error, totalZerr_bootstrapped, logZerr, remainderZerr)
				break
			# we want to make maxContribution as small as possible
			#   but if it becomes 10% of logZerr, that is enough
			if remainderZerr < logZerr / 10.: # and remainderZ < totalZ - log(10):
				pbar.finish()
				print 'tolerance will not improve: remainder error (%.3f) is much smaller than systematic errors (%.3f)' % (logZerr, remainderZerr)
				break
		
		widgets[0] = '|%d/%d samples+%d/%d|lnZ = %.2f +- %.3f + %.3f|L=%.2f @ %s' % (
			i + 1, pbar.maxval, sampler.nlive_points, sampler.ndraws, totalZ, logZerr, remainderZerr, Li,
			numpy.array_str(xi, max_line_width=1000, precision=4))
		ui, xi, Li = sampler.next()
		wi = logwidth + Li
		logZnew = logaddexp(logZ, wi)
		H = exp(wi - logZnew) * Li + exp(logZ - logZnew) * (H + logZ) - logZnew
		logZ = logZnew
	
	# not needed for integral, but for posterior samples, otherwise there
	# is a hole in the most likely parameter ranges.
	remainderZ, remainderZerr, totalZ, totalZerr, totalZerr_bootstrapped = integrate_remainder(sampler, logwidth, logVolremaining, logZ, H, sampler.Lmax)
	weights += [[ui, xi, Li, logwidth] for ui, xi, Li in sampler.remainder()]
	if need_robust_remainder_error:
		totalZerr = max(totalZerr, totalZerr_bootstrapped)
	return dict(logZ=totalZ, logZerr=totalZerr, 
		samples=sampler.samples, weights=weights, information=H,
		niterations=i)

__all__ = [nested_integrator]

