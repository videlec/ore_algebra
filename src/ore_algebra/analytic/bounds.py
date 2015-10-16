# -*- coding: utf-8 - vim: tw=80
"""
Error bounds

FIXME: silence deprecation warnings::

    sage: def ignore(*args): pass
    sage: sage.misc.superseded.warning=ignore
"""

# TODO:
# - this module uses at least three different object types for things that are
# essentially rational fractions (QuotientRingElements, Factorizations, and
# Rational Majorants) --> simplify?

import logging, warnings

import sage.rings.polynomial.real_roots as real_roots

from sage.misc.misc_c import prod
from sage.rings.all import CIF
from sage.rings.complex_ball_acb import CBF
from sage.rings.infinity import infinity
from sage.rings.integer import Integer
from sage.rings.polynomial.polynomial_element import Polynomial
from sage.rings.polynomial.polynomial_ring_constructor import PolynomialRing
from sage.rings.power_series_ring import PowerSeriesRing
from sage.rings.rational_field import QQ
from sage.rings.real_arb import RBF
from sage.rings.real_mpfi import RIF
from sage.rings.real_mpfr import RR
from sage.structure.factorization import Factorization

from ore_algebra.ore_algebra import OreAlgebra

from ore_algebra.analytic import utilities
from ore_algebra.analytic.safe_cmp import *

logger = logging.getLogger(__name__)

IR, IC = RBF, CBF # TBI

class BoundPrecisionError(Exception):
    pass

######################################################################
# Majorant series
######################################################################

class MajorantSeries(object):
    r"""
    A formal power series with nonnegative coefficients
    """

    def __init__(self, variable_name, cvrad=IR.zero()):
        self.variable_name = variable_name
        self.cvrad = IR(cvrad)
        assert self.cvrad >= IR.zero()

    def eval(self, ev):
        r"""
        Evaluate this majorant using the evaluator ``ev``.

        Typically the evaluator is a converter to a parent that supports all the
        basic operations (+*/, integral...) appearing in the expression of the
        majorant.
        """
        raise NotImplementedError

    def __call__(self, z):
        return self.eval(lambda obj: obj(z))

    def series(self, prec=10):
        Series = PowerSeriesRing(IR, self.variable_name, default_prec=prec)
        return self.eval(Series).truncate_powerseries(prec)

    def bound(self, rad, **kwds):
        if not safe_le(rad, self.cvrad): # intervals!
            return IR(infinity)
        else:
            return self._bound(rad, **kwds)

    def _bound(self, rad):
        return self(rad)

    def _test(self, fun=0, prec=50, return_difference=False):
        r"""
        Check that ``self`` is *plausibly* a majorant of ``fun``.

        This function in intended for debugging purposes. It does *not* perform
        a rigorous check that ``self`` is a majorant series of ``fun``, and may
        yield false positives (but no false negatives).

        The reference function ``fun`` should be convertible to a series with
        complex ball coefficients. If ``fun`` is omitted, check that ``self``
        has nonnegative coefficients.

        TESTS::

            sage: from ore_algebra.analytic.bounds import *
            sage: from sage.rings.real_arb import RBF
            sage: Pol.<z> = RBF[]
            sage: maj = RationalMajorant(Pol(1), Factorization([(1-z,1)]), Pol(0))
            sage: maj._test(11/10*z^30)
            Traceback (most recent call last):
            ...
            AssertionError: (30, [-0.10000000000000 +/- 8.00e-16], '< 0')
        """
        Series = PowerSeriesRing(IR, self.variable_name, prec)
        # CIF to work around problem with sage power series, should be IC
        ComplexSeries = PowerSeriesRing(CIF, self.variable_name, prec)
        maj = self.series(prec)
        ref = Series([iv.abs() for iv in ComplexSeries(fun)], prec=prec)
        delta = (maj - ref).padded_list()
        if len(delta) < prec:
            warnings.warn("checking {} term(s) instead of {} (cancellation"
                    " during series expansion?)".format(len(delta), prec))
        for i, c in enumerate(delta):
            # the lower endpoint of a coefficient of maj is not a bound in
            # general, and the series expansion can overestimate the
            # coefficients of ref
            if c < IR.zero():
                raise AssertionError(i, c, '< 0')
        if return_difference:
            return delta

def _pole_free_rad(fac):
    if isinstance(fac, Factorization):
        den = [pol for (pol, mult) in fac if mult < 0]
        if all(pol.degree() == 1 and pol.leading_coefficient().abs().is_one()
               for pol in den):
            rad = IR(infinity).min(*(IR(pol[0].abs()) for pol in den))
            rad = IR(rad.lower())
            assert rad >= IR.zero()
            return rad
    raise NotImplementedError  # pb dérivées???

class RationalMajorant(MajorantSeries):
    """
    A rational power series with nonnegative coefficients, represented in the
    form pol + num/den.

    TESTS::

        sage: from ore_algebra.analytic.bounds import *
        sage: from sage.rings.real_arb import RBF
        sage: Pol.<z> = RBF[]
        sage: den = Factorization([(1-z, 2), (2-z, 1)])
        sage: maj = RationalMajorant(z^2, den, 1 + z); maj
        1.000... + 1.000...*z + z^2/((-z + 2.000...) * (-z + 1.000...)^2)
        sage: maj(z).parent()
        Fraction Field of Univariate Polynomial Ring in z over Real ball field
        with 53 bits precision
        sage: maj(1/2)
        [2.166...]
        sage: maj*(z^10)
        1.000...*z^10 + 1.000...*z^11 + z^12/((-z + 2.000...) * (-z + 1.000...)^2)
        sage: maj.bound_antiderivative()
        1.00...*z + 0.50...*z^2 + [0.33...]*z^3/((-z + 2.00...) * (-z + 1.00...)^2)
        sage: maj.cvrad
        1.000000000000000
        sage: maj.series(4)
        1.000... + 1.000...*z + 0.500...*z^2 + 1.250...*z^3 + O(z^4)
        sage: maj._test()
        sage: maj._test(1 + z + z^2/((1-z)^2*(2-z)), return_difference=True)
        [0, 0, 0, ...]
        sage: maj._test(1 + z + z^2/((1-z)*(2-z)), return_difference=True)
        [0, 0, 0, 0.5000000000000000, 1.250000000000000, ...]
    """

    def __init__(self, num, den, pol):
        if isinstance(num, Polynomial) and isinstance(den, Factorization):
            Poly = num.parent().change_ring(IR)
            if not den.unit().is_one():
                raise ValueError("expected a denominator with unit part 1")
            assert num.valuation() > pol.degree()
            assert den.universe() is Poly or den.value() == 1
            super(self.__class__, self).__init__(Poly.variable_name(),
                    cvrad=_pole_free_rad(~den))
            self.num = Poly(num)
            self.pol = Poly(pol)
            self.den = den
            self.var = Poly.gen()
        else:
            raise TypeError

    def __repr__(self):
        res = ""
        if self.pol:
            Poly = self.pol.parent()
            pol_as_series = Poly.completion(Poly.gen())(self.pol)
            res += repr(pol_as_series) + " + "
        res += self.num._coeff_repr()
        if self.den:
            res += "/(" + repr(self.den) + ")"
        return res

    def eval(self, ev):
        # may by better than den.value()(z) in some cases
        den = prod(ev(lin)**mult for (lin, mult) in self.den)
        return ev(self.pol) + ev(self.num)/den

    def bound_antiderivative(self):
        # When u, v have nonneg coeffs, int(u·v) is majorized by int(u)·v.
        # This is a little bit pessimistic but yields a rational bound,
        # avoiding antiderivatives of rational functions.
        return RationalMajorant(self.num.integral(),
                                self.den,
                                self.pol.integral())

    def __mul__(self, pol):
        """"
        Multiplication by a polynomial.

        Note that this does not change the radius of convergence.
        """
        if pol.parent() is self.num.parent():
            return RationalMajorant(self.num*pol, self.den, self.pol*pol)
        else:
            raise TypeError

class HyperexpMajorant(MajorantSeries):
    """
    A formal power series of the form rat1(z) + exp(int(rat2(ζ), ζ=0..z)), with
    nonnegative coefficients.

    TESTS::

        sage: from ore_algebra.analytic.bounds import *
        sage: from sage.rings.real_arb import RBF
        sage: Pol.<z> = RBF[]
        sage: integrand = RationalMajorant(z^2, Factorization([(1-z,1)]), 4+4*z)
        sage: rat = Factorization([(1/3-z, -1)])
        sage: maj = HyperexpMajorant(integrand, rat); maj
        ((-z + [0.333...])^-1)*exp(int(4.0... + 4.0...*z + z^2/(-z + 1.0...)))
        sage: maj.cvrad
        [0.333...]
        sage: maj.series(4)
        [3.000...] + [21.000...]*z + [93.000...]*z^2 + [336.000...]*z^3 + O(z^4)
        sage: maj._test()
    """

    def __init__(self, integrand, rat):
        if isinstance(integrand, RationalMajorant) and isinstance(rat,
                Factorization):
            cvrad = integrand.cvrad.min(_pole_free_rad(rat))
            super(self.__class__, self).__init__(integrand.variable_name, cvrad)
            self.integrand = integrand
            self.rat = rat
        else:
            raise TypeError

    def __repr__(self):
        return "({})*exp(int({}))".format(self.rat, self.integrand)

    def eval(self, ev):
        integrand = self.integrand.eval(ev)
        return ev(self.rat.value()) * integrand.integral().exp()

    def _bound(self, rad, derivatives=1):
        """
        Bound the Frobenius norm of the vector

            [g(rad), g'(rad), g''(rad)/2, ..., 1/(d-1)!·g^(d-1)(rad)]

        where d = ``derivatives`` and g is this majorant series. The result is
        a bound for

            [f(z), f'(z), f''(z)/2, ..., 1/(d-1)!·f^(d-1)(z)]

        for all z with |z| ≤ rad.
        """
        rat = self.rat.value()
        # Compute the derivatives by “automatic differentiation”. This is
        # crucial for performance with operators of large order.
        Series = PowerSeriesRing(IR, 'eps', default_prec=derivatives)
        pert_rad = Series([rad, 1], derivatives)
        ser = rat(pert_rad)*self.integrand(pert_rad).integral().exp()
        rat_part = sum(coeff**2 for coeff in ser.truncate(derivatives))
        exp_part = (2*self.integrand.bound_antiderivative()(rad)).exp()
        return (rat_part*exp_part).sqrt() # XXX: sqrtpos?

    def __mul__(self, pol):
        """"
        Multiplication by a polynomial.

        Note that this does not change the radius of convergence.
        """
        return HyperexpMajorant(self.integrand, self.rat*pol)

######################################################################
# Majorants for reciprocals of polynomials ("denominators")
######################################################################

def graeffe(pol):
    r"""
    Compute the Graeffe iterate of this polynomial.

    EXAMPLES:

        sage: from ore_algebra.analytic.bounds import graeffe
        sage: Pol.<x> = QQ[]

        sage: pol = 6*x^5 - 2*x^4 - 2*x^3 + 2*x^2 + 1/12*x^2^2
        sage: sorted(graeffe(pol).roots(CC))
        [(0.000000000000000, 2), (0.110618733062304 - 0.436710223946931*I, 1),
        (0.110618733062304 + 0.436710223946931*I, 1), (0.547473953628478, 1)]
        sage: sorted([(z^2, m) for z, m in pol.roots(CC)])
        [(0.000000000000000, 2), (0.110618733062304 - 0.436710223946931*I, 1),
        (0.110618733062304 + 0.436710223946931*I, 1), (0.547473953628478, 1)]

    TESTS::

        sage: graeffe(CIF['x'].zero())
        0
        sage: graeffe(RIF['x'](-1/3))
        0.1111111111111111?
    """
    deg = pol.degree()
    Parent = pol.parent()
    pol_even = Parent([pol[2*i]   for i in xrange(deg/2+1)])
    pol_odd = Parent([pol[2*i+1] for i in xrange(deg/2+1)])
    graeffe_iterate = (-1)**deg * (pol_even**2 - (pol_odd**2).shift(1))
    return graeffe_iterate

def abs_min_nonzero_root(pol, tol=RR(1e-2), lg_larger_than=RR('-inf')):
    r"""
    Compute an enclosure of the absolute value of the nonzero complex root of
    ``pol`` closest to the origin.

    INPUT:

    - ``pol`` -- Nonzero polynomial.

    - ``tol`` -- An indication of the required relative accuracy (interval
      width over exact value). It is currently *not* guaranteed that the
      relative accuracy will be smaller than ``tol``.

    - ``lg_larger_than`` -- A lower bound on the binary logarithm of acceptable
      results. The function may loop if ``exact result <= 2^lg_larger_than``.

    ALGORITHM:

    Essentially the method of Davenport & Mignotte (1990).

    LIMITATIONS:

    The implementation currently works with a fixed precision. In extreme cases,
    it may fail if that precision is not large enough.

    EXAMPLES::

        sage: from ore_algebra.analytic.bounds import abs_min_nonzero_root
        sage: Pol.<z> = QQ[]
        sage: pol = 1/10*z^3 + z^2 + 1/7
        sage: sorted(z[0].abs() for z in pol.roots(CC))
        [0.377695553183559, 0.377695553183559, 10.0142451007998]

        sage: abs_min_nonzero_root(pol)
        [0.38 +/- 3.31e-3]

        sage: abs_min_nonzero_root(pol, tol=1e-10)
        [0.3776955532 +/- 2.41e-11]

        sage: abs_min_nonzero_root(pol, lg_larger_than=-1.4047042967)
        [0.3776955532 +/- 2.41e-11]

        sage: abs_min_nonzero_root(pol, lg_larger_than=-1.4047042966)
        Traceback (most recent call last):
        ...
        ValueError: there is a root smaller than 2^(-1.40470429660000)

        sage: abs_min_nonzero_root(pol, tol=1e-100)
        Traceback (most recent call last):
        ...
        ArithmeticError: failed to bound the roots ...

        sage: abs_min_nonzero_root(Pol.zero())
        Traceback (most recent call last):
        ...
        ValueError: expected a nonzero polynomial

    TESTS::

        sage: abs_min_nonzero_root(CBF['x'].one())
        +Infinity
        sage: abs_min_nonzero_root(CBF['x'].gen())
        +Infinity
        sage: abs_min_nonzero_root(CBF['x'].gen() - 1/3)
        [0.33 +/- 3.34e-3]
    """
    if pol.is_zero():
        raise ValueError("expected a nonzero polynomial")
    pol >>= pol.valuation()
    deg = pol.degree()
    if deg == 0:
        return infinity
    pol = pol/pol[0]
    pol = pol.change_ring(IR.complex_field())
    i = 0
    lg_rad = RIF(-infinity, infinity)          # left-right intervals because we
    encl = RIF(1, 2*deg).log(2)                # compute intersections
    while (safe_le(lg_rad.lower(rnd='RNDN'), lg_larger_than)
              # *relative* error on 2^lg_rad
           or safe_gt(lg_rad.absolute_diameter(), tol)):
        prev_lg_rad = lg_rad
        # The smallest root of the current pol is between 2^(-1-m) and
        # (2·deg)·2^(-1-m), cf. Davenport & Mignotte (1990), Grégoire (2012).
        m = IR(-infinity).max(*(pol[k].abs().log(2)/k
                                for k in xrange(1, deg+1)))
        lg_rad = (-(1 + RIF(m)) + encl) >> i
        lg_rad = prev_lg_rad.intersection(lg_rad)
        if lg_rad.lower() == -infinity or cmp(lg_rad, prev_lg_rad) == 0:
            fmt = "failed to bound the roots of {} (insufficient precision?)"
            raise ArithmeticError(fmt.format(pol)) # TODO: BoundPrecisionError?
        logger.log(logging.DEBUG - 1, "i = %s\trad ∈ %s\tdiam=%s",
                i, lg_rad.exp2().str(style='brackets'),
                lg_rad.absolute_diameter())
        # detect gross input errors (this does not prevent all infinite loops)
        if safe_le(lg_rad.upper(rnd='RNDN'), lg_larger_than):
            raise ValueError("there is a root smaller than 2^({})"
                             .format(lg_larger_than))
        pol = graeffe(pol)
        i += 1
    res = IR(2)**IR(lg_rad)
    if not safe_le(2*res.rad_as_ball()/res, IR(tol)):
        logger.debug("required tolerance may not be met")
    return res

def bound_inverse_poly(den, algorithm="simple"):
    """
    Return a majorant series ``cst/fac`` for ``1/den``, as a pair ``(cst, fac)``
    where ``fac`` is a ``Factorization`` object with linear factors.

    EXAMPLES::

        sage: from ore_algebra.analytic.bounds import *
        sage: Pol.<x> = QQ[]
        sage: pol = 2*x + 1
        sage: cst, den = bound_inverse_poly(pol)
        sage: maj = RationalMajorant(Pol(cst), den, Pol(0)); maj
        0.5000000000000000/(-x + [0.4972960558102933 +/- 4.71e-17])
        sage: maj._test(1/pol)

    TESTS::

        sage: for pol in [Pol(1), Pol(-42), 2*x+1, x^3 + x^2 + x + 1, 5*x^2-7]:
        ....:     for algo in ['simple', 'solve']:
        ....:         cst, den = bound_inverse_poly(pol, algorithm=algo)
        ....:         maj = RationalMajorant(Pol(0)+cst, den, Pol(0))
        ....:         maj._test(1/pol)
    """
    Poly = den.parent().change_ring(IR)
    if den.degree() <= 0:
        factors = []
    else:
        # below_abs()/lower() to get thin intervals
        if algorithm == "simple":
            rad = abs_min_nonzero_root(den).below_abs(test_zero=True)
            factors = [(Poly([rad, -1]), den.degree())]
        elif algorithm == "solve":
            poles = den.roots(CIF)
            factors = [(Poly([IR(iv.abs().lower()), -1]), mult)
                        for iv, mult in poles]
        else:
            raise ValueError("algorithm")
    num = ~abs(IC(den.leading_coefficient()))
    return num, Factorization(factors, unit=Poly(1))

######################################################################
# Bounds on rational functions of n
######################################################################

class RatSeqBound(object):
    r"""
    A piecewise-constant-piecewise-rational nonincreasing sequence.

    This is intended to represent a sequence b(n) such that |f(k)| <= b(n) for
    all k >= n, for a certain (rational) sequence f(n) = num(n)/den(n). The
    bound is defined by

    - the two polynomials num, den, with deg(num) <= deg(den),

    - and a list of pairs (n[i], v[i]) with n[i-1] <= n[i], n[-1] = ∞,
      v[i-1] <= v[i], and such that

          |f(k)| <= max(|f(n)|, v[i]) for n[i-1] < n <= k <= n[i].
    """

    def __init__(self, num, den, stairs):
        self.num = num
        self.den = den
        self.stairs = stairs

    def __repr__(self):
        fmt = "max(\n  |({num})/({den})|,\n{stairs}\n)"
        n = self.num.variable_name()
        stairsstr = ',\n'.join("  {}\tfor  {} <= {}".format(val, n, edge)
                                for edge, val in self.stairs)
        r = fmt.format(num=self.num, den=self.den, stairs=stairsstr)
        return r

    def stairs_step(self, n):
        for (edge, val) in self.stairs:
            if n <= edge:
                return val
        assert False

    def __call__(self, n):
        step = self.stairs_step(n)
        if step.upper() == infinity: # TODO: arb is_finite?
            return step
        else:
            # TODO: avoid recomputing cst every time once it becomes <= next + ε?
            val = (IC(self.num(n))/IC(self.den(n))).above_abs()
            return step.max(val)

    def plot(self, n=30):
        from sage.plot.plot import list_plot
        rat = self.num/self.den
        p1 = list_plot([RR(abs(rat(k))) if self.den(k) else RR('inf')
                        for k in range(n)],
                marker='o', plotjoined=True)
        p2 = list_plot([self.stairs_step(k).upper() for k in range(n)],
                plotjoined=True, linestyle=':', color='black')
        p3 = list_plot([self(k).upper() for k in range(n)],
                marker='o', plotjoined=True, color='blue')
        return p1 + p2 + p3

    def _test(self, n=100):
        for k in range(n):
            if self(k) < IR(self.num(k)/self.den(k)).abs():
                raise AssertionError

def bound_real_roots(pol):
    if pol.is_zero(): # XXX: may not play well with intervals
        return -infinity
    bound = real_roots.cl_maximum_root(pol.change_ring(RIF).list())
    bound = RIF._upper_field()(bound) # work around weakness of cl_maximum_root
    bound = bound.nextabove().ceil()
    return bound

# TODO: share code with the main implementation (if I keep both versions)
def bound_ratio_large_n_nosolve(num, den, stats=None):
    """
    Given two polynomials num and den, return a function a(n) such that

        0 < |num(k)| < a(n)·|den(k)|

    for all k >= n >= 0. Note that a may take infinite values.

    This version accepts polynomials with interval coefficients, but yields less
    tight bounds than ``bound_ratio_large_n_solve``.

    EXAMPLES::

        sage: from ore_algebra.analytic.bounds import bound_ratio_large_n_nosolve
        sage: Pols.<n> = QQ[]

        sage: num = (n^3-2/3*n^2-10*n+2)*(n^3-30*n+8)*(n^3-10/9*n+1/54)
        sage: den = (n^3-5/2*n^2+n+2/5)*(n^3-1/2*n^2+3*n+2)*(n^3-81/5*n-14/15)
        sage: bnd = bound_ratio_large_n_nosolve(num, den); bnd
        max(
          ...
          [+/- inf]             for  n <= 0,
          [22.77...]            for  n <= 23,
          1.000000000000000     for  n <= +Infinity
        )
        sage: bnd.plot().show(ymax=30); bnd._test()

        sage: from sage.rings.complex_ball_acb import CBF
        sage: num, den = num.change_ring(CBF), den.change_ring(CBF)
        sage: bound_ratio_large_n_nosolve(num, den)
        max(
          ...
          [+/- inf]             for  n <= 0,
          [22.77...]            for  n <= 23,
          1.000000000000000     for  n <= +Infinity
        )
    """
    rat = num/den
    num, den = rat.numerator(), rat.denominator()

    if num.degree() > den.degree():
        raise ValueError("expected deg(num) <= deg(den)")

    def sqn(pol):
        RealScalars = num.base_ring().base_ring()
        re, im = (pol.map_coefficients(which, new_base_ring=RealScalars)
                  for which in (lambda coef: coef.real(),
                                lambda coef: coef.imag()))
        return re**2 + im**2
    sqn_num, sqn_den = sqn(num), sqn(den)
    crit = sqn_num.diff()*sqn_den - sqn_den.diff()*sqn_num

    finite_from = max(2, bound_real_roots(sqn_den))
    monotonic_from = max(finite_from, bound_real_roots(crit))

    orig_den = den
    num = num.change_ring(IC)
    den = den.change_ring(IC)
    def bound_term(n): return num(n).abs()/den(n).abs()
    lim = (num[den.degree()]/den.leading_coefficient()).abs()

    # We would compute these later anyway (unless we are more clever here)
    last = 0
    nonincr_or_le_lim_from = None
    finite_from = 0
    logger.debug("monotonic from %s, starting extended search", monotonic_from)
    if stats: stats.time_staircases.tic()
    for n in xrange(monotonic_from, 0, -1):
        val = bound_term(n)
        if (nonincr_or_le_lim_from is None
                and not (val <= lim)
                and not (val >= last)): # interval comparisons
            nonincr_or_le_lim_from = n + 1
        if not orig_den(n):
            finite_from = n + 1
            break
        last = val
    if nonincr_or_le_lim_from is None:
        nonincr_or_le_lim_from = finite_from # TBI?

    ini_range = xrange(finite_from, nonincr_or_le_lim_from+1) # +1 for clarity when empty
    ini_bound = lim.max(*(bound_term(n) for n in ini_range))
    if stats: stats.time_staircases.toc()

    logger.debug("finite from %s, ini_bound=%s, ↘/≤lim from %s, lim=%s",
            finite_from, ini_bound, nonincr_or_le_lim_from, lim)

    stairs = [(finite_from, IR(infinity)), (nonincr_or_le_lim_from, ini_bound),
              (infinity, lim)]
    return RatSeqBound(num, den, stairs)

def nonneg_roots(pol):
    bound = bound_real_roots(pol)
    roots = real_roots.real_roots(pol, bounds=(QQ(0), bound))
    if roots and roots[-1][0][1]:
        diam = ~roots[-1][0][1]
        while any(rt - lt > QQ(10) for ((lt, rt), _) in roots):
            # max_diameter is a relative diameter --> pb for large roots
            logger.debug("largest root diameter = %s, refining",
                    roots[-1][0][1] - roots[-1][0][0].n(10))
            roots = real_roots.real_roots(pol, bounds=(QQ(0), bound),
                                          max_diameter=diam)
            diam >>= 1
    return roots

upper_inf = RIF(infinity).upper()

def bound_ratio_large_n_solve(num, den, min_drop=IR(1.1), stats=None):
    """
    Given two polynomials num and den, return a function b(n) such that

        0 < |num(k)| < b(n)·|den(k)|

    for all k >= n >= 0. Note that b may take infinite values.

    EXAMPLES::

        sage: from ore_algebra.analytic.bounds import bound_ratio_large_n_solve
        sage: Pols.<n> = QQ[]

        sage: num = (n^3-2/3*n^2-10*n+2)*(n^3-30*n+8)*(n^3-10/9*n+1/54)
        sage: den = (n^3-5/2*n^2+n+2/5)*(n^3-1/2*n^2+3*n+2)*(n^3-81/5*n-14/15)
        sage: bnd1 = bound_ratio_large_n_solve(num, den); bnd1
        max(
          |(n^9 + ([-0.66...])*n^8 + ([-41.1...])*n^7 + ...)/(n^9 - ...)|,
          [22.77116...]     for  n <= 2,
          [12.72438...]     for  n <= 4,
          [1.052785...]     for  n <= +Infinity
        )
        sage: bnd1.plot(12)
        Graphics object consisting of 3 graphics primitives

        sage: num = (n^2-3/2*n-6/7)*(n^2+1/8*n+1/12)*(n^3-1/44*n^2+1/11*n+9/22)
        sage: den = (n^3-1/2*n^2+1/13)*(n^3-28*n+35)*(n^3-31/5)
        sage: bnd2 = bound_ratio_large_n_solve(num, den); bnd2
        max(
          ...
          [0.231763...]   for  n <= 4,
          [0.200420...]   for  n <= 5,
          0               for  n <= +Infinity
        )
        sage: bnd2.plot()
        Graphics object consisting of 3 graphics primitives

    TESTS::

        sage: bnd1._test()
        sage: bnd2._test()

        sage: bound_ratio_large_n_solve(n, Pols(1))
        Traceback (most recent call last):
        ...
        ValueError: expected deg(num) <= deg(den)

        sage: bound_ratio_large_n_solve(Pols(1), Pols(3))
        max(
          |([0.333...])/(1.000...)|,
          [0.333...]     for  n <= +Infinity
        )

        sage: i = QuadraticField(-1).gen()
        sage: bound_ratio_large_n_solve(n, n + i)
        max(
          |(n)/(n + I)|,
          1.000000000000000     for  n <= +Infinity
        )
    """
    rat = num/den
    num, den = rat.numerator(), rat.denominator()

    if num.is_zero():
        return RatSeqBound(num, den, [(infinity, IR.zero())])
    if num.degree() > den.degree():
        raise ValueError("expected deg(num) <= deg(den)")

    def sqn(pol):
        RealScalars = num.base_ring().base_ring()
        re, im = (pol.map_coefficients(which, new_base_ring=RealScalars)
                  for which in (lambda coef: coef.real(),
                                lambda coef: coef.imag()))
        return re**2 + im**2
    sqn_num, sqn_den = sqn(num), sqn(den)
    crit = sqn_num.diff()*sqn_den - sqn_den.diff()*sqn_num

    if stats: stats.time_roots.tic()
    roots = nonneg_roots(sqn_den) # we want real coefficients
    roots.extend(nonneg_roots(crit))
    roots = [descr[0] for descr in roots] # throw away mults
    if stats: stats.time_roots.toc()

    if stats: stats.time_staircases.tic()
    num, den = num.change_ring(IC), den.change_ring(IC)
    thrs = set(n for iv in roots for n in xrange(iv[0].floor(), iv[1].ceil()))
    thrs = list(thrs)
    thrs.sort(reverse=True)
    thr_vals = [(n, num(n).abs()/den(n).abs()) for n in thrs]
    lim = (num[den.degree()]/den.leading_coefficient()).abs()
    stairs = [(infinity, lim)]
    for (n, val) in thr_vals:
        if val.upper() > (min_drop*stairs[-1][1]).upper():
            stairs.append((n, val))
        elif val.upper() > stairs[-1][1].upper():
            # avoid unnecessarily large staircases
            stairs[-1] = (stairs[-1][0], val)
        if val.upper() == upper_inf:
            break
    stairs.reverse()
    logger.debug("done building staircase, size = %s", len(stairs))
    if stats: stats.time_staircases.toc()

    return RatSeqBound(num, den, stairs)

bound_ratio_large_n = bound_ratio_large_n_solve

################################################################################
# Bounds for differential equations
################################################################################

def bound_polynomials(pols):
    r"""
    Compute a common majorant polynomial for the polynomials in ``pol``.

    Note that this returns a _majorant_, not some kind of enclosure.

    TESTS::

        sage: from ore_algebra.analytic.bounds import bound_polynomials
        sage: Pol.<z> = PolynomialRing(QuadraticField(-1, 'i'), sparse=True)
        sage: bound_polynomials([(-1/3+z) << (10^10), (-2*z) << (10^10)])
        2.000...*z^10000000001 + [0.333...]*z^10000000000
        sage: bound_polynomials([Pol(0)])
        0
        sage: bound_polynomials([])
        Traceback (most recent call last):
        ...
        IndexError: list index out of range
    """
    assert isinstance(pols, list)
    PolyIC = pols[0].parent().change_ring(IC)
    deg = max(pol.degree() for pol in pols)
    val = min(deg, min(pol.valuation() for pol in pols))
    pols = [PolyIC(pol) for pol in pols] # TBI
    order = Integer(len(pols))
    PolyIR = PolyIC.change_ring(IR)
    def coeff_bound(n):
        return IR.zero().max(*(
            pols[k][n].above_abs()
            for k in xrange(order)))
    maj = PolyIR([coeff_bound(n)
                  for n in xrange(val, deg + 1)])
    maj <<= val
    return maj

class DiffOpBound(object):
    r"""
    A "bound on the inverse" of a differential operator at an ordinary point.

    This is an object that, given a residual q = dop·ỹ where ỹ(z) = c·z^N + ···
    is the truncation of degree N of a solution y of dop·y = 0, is able to
    compute a majorant series of the tail y(z) - ỹ(z). The majorant series of
    the tail is represented by a HyperexpMajorant.

    Note that multiplying dop by a rational function changes the residual.

    More precisely, a DiffOpBound represents a *sequence* v[n](z) of formal
    power series with the property that, if N and ỹ are as above with N >= n,
    then v[n](z)·B(q)(z), for some polynomial B(q) derived from q, is a majorant
    of y(z) - ỹ(z). Here B(q) can be taken to be any majorant polynomial of q,
    but tighter choices are possible (see below for details).

    The sequence v[n](z) is of the form

        1/den(z) * exp(int(cst*num[n](z)/den(z) + pol[n](z)))

    where

    * num[n](z) and pol[n](z) are polynomials with coefficients depending on n
      (given by RatSeqBound objects), with val(num[n]) >= deg(pol[n]),

    * den(z) is a polynomial (with constant coefficients),

    * cst is a constant.

    EXAMPLES::

        sage: from ore_algebra.analytic.ui import *
        sage: from ore_algebra.analytic.bounds import *
        sage: Dops, x, Dx = Diffops()

    A majorant sequence::

        sage: maj = bound_diffop((x^2 + 1)*Dx^2 + 2*x*Dx); maj
        1/((-x + [0.994...])^2)*exp(int(1.000...*NUM/(-x + [0.994...])^2+POL))
        where
        NUM=max(
          |(0)/(1)|,
          0     for  n <= +Infinity
        )*z^0 + max(
          |(-2.000...*n - 2.000...)/(n - 1.000...)|,
          [+/- inf]     for  n <= 1,
          2.000...     for  n <= +Infinity
        )*z^1
        POL=

    A majorant series extracted from that sequence::

        sage: maj(3)
        ((-x + [0.994...])^-2)*exp(int(4.000...])^2)))
    """

    def __init__(self, dop, cst, majseq_pol_part, majseq_num, maj_den):
        r"""
        INPUT:

        - ``dop`` - the operator to which the bound applies (and which should be
          used to compute the residuals),

        - ``cst`` - constant (real ball),

        - ``majseq_pol_part`` - *list* of coefficients of ``pol_part``,

        - ``majseq_num`` - *list* of coefficients [c[d], c[d+1], ...] of
          ``num``, starting at degree d = deg(pol_part) + 1,

        - ``maj_den`` - ``Factorization``.
        """
        self.dop = dop
        self.Poly = dop.base_ring().change_ring(IR)
        self.cst = cst
        self.majseq_pol_part = majseq_pol_part
        self.majseq_num = majseq_num
        self.maj_den = maj_den

    def __repr__(self):
        fmt = ("1/({den})*exp(int({cst}*NUM/{den}+POL))\n"
               "where\n"
               "NUM={num}\n"
               "POL={pol}")
        def pol_repr(ratseqbounds, shift=0):
            return " + ".join("{}*z^{}".format(c, n + shift)
                              for n, c in enumerate(ratseqbounds))
        return fmt.format(
                cst=self.cst, den=self.maj_den,
                num=pol_repr(self.majseq_num, shift=len(self.majseq_pol_part)),
                pol=pol_repr(self.majseq_pol_part))

    def __call__(self, n):
        r"""
        Return a term of the majorant sequence.
        """
        maj_pol_part = self.Poly([fun(n) for fun in self.majseq_pol_part])
        maj_num = (self.Poly([fun(n) for fun in self.majseq_num])
                << len(self.majseq_pol_part))
        rat_maj = RationalMajorant(self.cst*maj_num, self.maj_den, maj_pol_part)
        maj = HyperexpMajorant(integrand=rat_maj, rat=~self.maj_den)
        return maj

    def tail_majorant(self, n, residuals):
        r"""
        Bound the tails of order ``N`` of solutions of ``self.dop(y) == 0``.

        INPUT:

        - ``n`` - integer, ``n <= N``, typically ``n == N``. (Technically, this
          function should work for ``n < N `` too, but this is unused, untested,
          and not very useful with the current code structure.)

        - ``residuals`` - list of polynomials of the form ``self.dop(y[:N])``
          where y satisfies ``self.dop(y) == 0``.

        OUTPUT:

        A (common) majorant series of the tails ``y[N:](z)`` of the solutions
        corresponding to the elements of ``residuals``.
        """
        abs_residual = bound_polynomials(residuals)
        # In general, a majorant series for the tails of order n is given by
        # self(n)(z)*int(t⁻¹*qq(t)/self(n)(t)) where qq(t) is a polynomial s.t.
        # |qq[k]| >= (k/indicial_eq(k))*abs_residual[k]. Since k/indicial_eq(k)
        # <= 1 (ordinary point!), we can take qq = abs_residual. (We lose a
        # factor of about n^(ordeq-1) on the final bound.) The resulting bound
        # is still not very convenient to compute. But since self(n) has
        # nonnegative coefficients and self(n)(0) = 1, we can even take qq =
        # abs_residual*self(n), which yields a very simple (if less tight)
        # bound. (XXX: How much do we lose in the second operation?)
        assert abs_residual.valuation() >= n >= self.dop.order() >= 1
        maj = self(n)*(abs_residual >> 1).integral()
        logger.debug("lc(abs_res) = %s", abs_residual.leading_coefficient())
        logger.debug("maj(%s) = %s", n, self(n))
        logger.debug("maj = %s", maj)
        return maj

    def matrix_sol_tail_bound(self, n, rad, residuals, ord=None):
        r"""
        Bound the Frobenius norm of the tail starting of order ``n`` of the
        series expansion of the matrix ``(y_j^(i)(z)/i!)_{i,j}`` where the
        ``y_j`` are the solutions associated to the elements of ``residuals``,
        and ``0 ≤ j < ord``. The bound is valid for ``|z| < rad``.
        """
        if ord is None: ord=self.dop.order()
        maj = self.tail_majorant(n, residuals)
        # Since (y[n:])' << maj => (y')[n:] << maj, this bound is valid for the
        # tails of a column of the form [y, y', y''/2, y'''/6, ...] or
        # [y, θy, θ²y/2, θ³y/6, ...].
        col_bound = maj.bound(rad, derivatives=ord)
        logger.debug("maj(%s).bound() = %s", n, self(n).bound(rad))
        logger.debug("col_bound = %s", col_bound)
        return IR(ord).sqrt()*col_bound

    def _test(self, ini=None, prec=50):
        r"""
        Check that the majorants produced by this DiffOpBound bound the tails of
        the solutions of the associated operator.

        This is a heuristic check for testing purposes, nothing rigorous!

        EXAMPLES::

            sage: from ore_algebra.analytic.ui import *
            sage: from ore_algebra.analytic.bounds import *
            sage: Dops, x, Dx = Diffops()
            sage: maj = bound_diffop(Dx - 1)
            sage: maj._test()
            sage: maj._test([3], 200)
        """
        ord = self.dop.order()
        if ini is None:
            from sage.rings.number_field.number_field import QuadraticField
            QQi = QuadraticField(-1)
            ini = [QQi.random_element() for _ in xrange(ord)]
        sol = self.dop.power_series_solutions(prec)
        Series = PowerSeriesRing(CBF, self.dop.base_ring().variable_name())
        ref = sum((ini[k]*sol[k] for k in xrange(ord)), Series(0)).polynomial()
        for n in [ord, ord + 1, ord + 2, ord + 10]:
            logger.info("truncation order = %d", n)
            if n + 5 >= prec:
                warnings.warn("insufficient precision")
            resid = self.dop(ref[:n])
            # we know a priori that val(resid) >= n mathematically, but interval
            # computations may give inexact zeros for some of the coefficients
            assert all(c.contains_zero() for c in resid[:n])
            resid = resid[n:]
            maj = self.tail_majorant(n, [resid])
            logger.info("%s << %s", Series(ref[n:], n+5), maj.series(n+5))
            maj._test(ref[n:])

# Perhaps better: work with a "true" Ore algebra K[θ][z]. Use Euclidean
# division to compute the truncation. Extracting the Qj(θ) would then be easy,
# and I may no longer need the coefficients of θ "on the right".

def _dop_rcoeffs_of_T(dop):
    """
    Compute the coefficients of dop as an operator in θ but with θ on the left.
    """
    Pols_z = dop.base_ring()
    Pols_n, n = Pols_z.change_var('n').objgen()
    Rops = OreAlgebra(Pols_n, 'Sn')
    rop = dop.to_S(Rops) if dop else Rops(0)
    bwd_rop_as_pol = (rop.polynomial().reverse().change_variable_name('Bn')
                         .map_coefficients(lambda pol: pol(n-rop.order())))
    MPol = Pols_n.extend_variables('Bn')
    bwd_rop_rcoeffof_n = MPol(bwd_rop_as_pol).polynomial(MPol.gen(0)).list()
    val = min(pol.valuation() for pol in dop.coefficients()
              + [Pols_z.zero()]) # TBI; 0 to handle dop=0
    res = [Pols_z(c) << val for c in bwd_rop_rcoeffof_n]
    assert dop.is_zero() or dop.leading_coefficient() == res[-1]
    return res

class BoundDiffopStats(utilities.Stats):
    """
    Store timings for various parts of the bound computation algorithm.
    """
    def __init__(self):
        super(self.__class__, self).__init__()
        self.time_roots = utilities.Clock("computing roots")
        self.time_staircases = utilities.Clock("building staircases")
        self.time_decomp_op = utilities.Clock("decomposing op")

def bound_diffop(dop, pol_part_len=0):
    r"""
    Compute a :class:`DiffOpBound` object that can be used to bound the tails of
    power series solutions of ``dop``.

    See the docstring of :class:`DiffOpBound` for more information.

    .. WARNING::

        The bounds depend on residuals computed using not ``dop`` itself, but a
        “normalized” operator obtained by multiplying it by a power of x. The
        normalized operator is returned in the ``dop`` field of the result.

    EXAMPLES::

        sage: from ore_algebra.analytic.ui import *
        sage: from ore_algebra.analytic.bounds import bound_diffop, _test_bound_diffop
        sage: Dops, x, Dx = Diffops()

        sage: bound_diffop(Dx - 1)
        1/(1.000...)*exp(int(1.000...*NUM/1.000...+POL))
        where
        NUM=max(
        |(-1.000...)/(1.000...)|,
        1.000...     for  n <= +Infinity
        )*z^0
        POL=

        sage: dop = (x+1)*(x^2+1)*Dx^3-(x-1)*(x^2-3)*Dx^2-2*(x^2+2*x-1)*Dx
        sage: bound_diffop(dop, pol_part_len=3) # not tested
        1/((-x + [0.9965035284306323 +/- 2.07e-17])^3)*
        exp(int(1.000...*NUM/(-x + [0.9965035284306323 +/- 2.07e-17])^3+POL))
        where
        NUM=max(
          |(-5.000...*n^2 - 7.000...*n - 2.000...)/(n^2 - 3.000...*n + 2.000...)|,
          [+/- inf]     for  n <= 2,
          34.000...     for  n <= 3,
          5.000...     for  n <= +Infinity
        )*z^2 + max(
          |(2.000...*n^2 + 8.000...*n + 4.000...)/(n^2 - 3.000...*n + 2.000...)|,
          [+/- inf]     for  n <= 2,
          23.000...     for  n <= 3,
          2.000...     for  n <= +Infinity
        )*z^3 + max(
          |(-3.000...*n^2 - 11.000...*n - 8.000...)/(n^2 - 3.000...*n + 2.000...)|,
          [+/- inf]     for  n <= 2,
          34.000...     for  n <= 3,
          3.000...     for  n <= +Infinity
        )*z^4
        POL=max(
          |(-6.000...)/(1.000...)|,
          6.000...     for  n <= +Infinity
        )*z^0 + max(
          |(3.000...*n - 1.000...)/(n - 1.000...)|,
          [+/- inf]     for  n <= 1,
          3.000...     for  n <= +Infinity
        )*z^1

    TESTS::

        sage: QQi.<i> = QuadraticField(-1)
        sage: for dop in [
        ....:     # orders <= 1 are not supported
        ....:     Dx, Dx - 1, i*Dx, Dx + i, Dx^2,
        ....:     (x^2 + 1)*Dx^2 + 2*x*Dx,
        ....:     Dx^2 - x*Dx
        ....: ]:
        ....:     bound_diffop(dop)._test()

        sage: _test_bound_diffop()
    """
    stats = BoundDiffopStats()
    _, Pols_z, _, dop = dop._normalize_base_ring()
    z = Pols_z.gen()
    lc = dop.leading_coefficient()
    if lc.is_term() and not lc.is_constant():
        raise ValueError("irregular singular operator", dop)
    rcoeffs = _dop_rcoeffs_of_T(dop)
    Trunc = Pols_z.quo(z**(pol_part_len+1))
    inv = ~Trunc(lc)
    MPol, (z, n) = Pols_z.extend_variables('n').objgens()
    # Including rcoeffs[-1] here is actually redundant, as by construction the
    # only term in first to involve n^ordeq will be 1·n^ordeq·z^0. But I find
    # the code easier to understand this way.
    first = sum(n**j*(Trunc(pol)*inv).lift()
                for j, pol in enumerate(rcoeffs))
    first_nz = first.polynomial(z)
    first_zn = first.polynomial(n)
    logger.debug("first: %s", first_nz)
    assert first_nz[0] == dop.indicial_polynomial(z, n).monic()
    assert all(pol.degree() < dop.order() for pol in first_nz[1:])

    stats.time_decomp_op.tic()
    dop_T = dop.to_T('T' + str(z)) # slow
    T = dop_T.parent().gen()
    pol_part = sum(T**j*pol for j, pol in enumerate(first_zn)) # slow
    logger.debug("pol_part: %s", pol_part)
    rem_num = dop_T - pol_part*lc # inefficient in theory for large pol_part_len
    logger.debug("rem_num: %s", rem_num)
    it = enumerate(_dop_rcoeffs_of_T(rem_num))
    rem_num_nz = MPol(sum(n**j*pol for j, pol in it)).polynomial(z)
    assert rem_num_nz.valuation() >= pol_part_len + 1
    rem_num_nz >>= (pol_part_len + 1)
    stats.time_decomp_op.toc()
    logger.debug("rem_num_nz: %s", rem_num_nz)

    ind = first_nz[0]
    cst, maj_den = bound_inverse_poly(lc)
    # Note that here we ignore the coefficient first_nz[0], which amounts to
    # multiplying the integrand of the DiffOpBound by z⁻¹, as prescribed by the
    # theory. Since majseq_num starts by definition at the degree following that
    # of majseq_pol_part, it gets shifted as well. The "<< 1" in the next few
    # lines have nothing to do with that, they are multiplications by *n*.
    majseq_pol_part = [bound_ratio_large_n(first_nz[i] << 1, ind, stats=stats)
                       for i in xrange(1, pol_part_len + 1)]
    majseq_num = [bound_ratio_large_n(pol << 1, ind, stats=stats)
                  for pol in rem_num_nz]
    assert len(majseq_pol_part) == pol_part_len
    maj = DiffOpBound(dop_T, cst, majseq_pol_part, majseq_num, maj_den)
    logger.debug("...done, time: %s", stats)
    return maj

def _test_bound_diffop(
        ords=xrange(1, 5),
        degs=xrange(5),
        pplens=[1, 2, 5],
        prec=50
    ):
    r"""
    Randomized testing of :func:`bound_diffop`.

    EXAMPLES::

        sage: import logging; logging.basicConfig(level=logging.INFO)
        sage: from ore_algebra.analytic.bounds import _test_bound_diffop
        sage: _test_bound_diffop() # not tested
        INFO:ore_algebra.analytic.bounds:testing operator: (-i + 2)*Dx + i - 1
        ...
    """
    from sage.rings.number_field.number_field import QuadraticField
    from ore_algebra import OreAlgebra

    QQi = QuadraticField(-1, 'i')
    Pols, x = PolynomialRing(QQi, 'x').objgen()
    Dops, Dx = OreAlgebra(Pols, 'Dx').objgen()

    for ord in ords:
        for deg in degs:
            dop = Dops(0)
            while dop.leading_coefficient()(0).is_zero():
                dop = Dops([Pols.random_element(degree=(0, deg))
                            for _ in xrange(ord + 1)])
            logger.info("testing operator: %s", dop)
            for pplen in pplens:
                maj = bound_diffop(dop, pol_part_len=pplen)
                maj._test(prec=prec)

def residual(bwrec, n, last, z):
    r"""
    Compute the polynomial residual, up to sign, obtained by a applying a diff
    op P to a partial sum of a power series solution y of P·y=0.

    INPUT:

    - ``bwrec`` -- list [b[0], ..., b[s]] of coefficients of the recurrence
      operator associated to P (by the direct substitution x |--> S⁻¹, θ |--> n;
      no additional multiplication by x^k is allowed!), written in the form
      b[0](n) + b[1](n) S⁻¹ + ···

    - ``n`` -- truncation order

    - ``last`` -- the last s+1 coefficients u[n-1], u[n-2], ... of the
      truncated series, in that order

    - ``z`` -- variable name for the result

    EXAMPLES::

        sage: from sage.rings.complex_ball_acb import CBF
        sage: from ore_algebra import OreAlgebra
        sage: from ore_algebra.analytic.bounds import *
        sage: Pol_t.<t> = QQ[]; Pol_n.<n> = QQ[]
        sage: Dop.<Dt> = OreAlgebra(Pol_t)

        sage: trunc = t._exp_series(5); trunc
        1/24*t^4 + 1/6*t^3 + 1/2*t^2 + t + 1
        sage: residual([n, Pol_n(1)], 5, [trunc[4]], t)
        ([0.0416666666666667 +/- 4.26e-17])*t^5
        sage: (Dt - 1).to_T('Tt')(trunc).change_ring(CBF)
        ([-0.0416666666666667 +/- 4.26e-17])*t^5

    Note that using Dt -1 instead of θt - t makes a difference in the result,
    since it amounts to a division by t::

        sage: (Dt - 1)(trunc).change_ring(CBF)
        ([-0.0416666666666667 +/- 4.26e-17])*t^4

    ::

        sage: trunc = t._sin_series(5) + t._cos_series(5)
        sage: residual([n*(n-1), Pol_n(0), Pol_n(1)], 5, [trunc[4], trunc[3]], t)
        ([0.041666...])*t^6 + ([-0.16666...])*t^5
        sage: (Dt^2 + 1).to_T('Tt')(trunc).change_ring(CBF)
        ([0.041666...])*t^6 + ([-0.16666...])*t^5
    """
    # NOTE: later on I may want to compute the residuals directly in each
    # implementation of summation, to avoid recomputing known quantities (as
    # this function currently does)
    ordrec = len(bwrec) - 1
    rescoef = [
        sum(IC(bwrec[i+k+1](n+i))*IC(last[k])
            for k in xrange(ordrec-i))
        for i in xrange(ordrec)]
    IvPols = PolynomialRing(IC, z, sparse=True)
    return IvPols(rescoef) << n

