# -*- coding: utf-8 - vim: tw=80
"""
Analytic continuation paths
"""

import logging

import sage.categories.pushout as pushout
import sage.plot.all as plot
import sage.rings.all as rings
import sage.rings.number_field.number_field as number_field
import sage.rings.number_field.number_field_base as number_field_base
import sage.symbolic.ring

from sage.misc.cachefunc import cached_method
from sage.rings.all import QQ, CC, RIF, CIF, QQbar, RLF, CLF, Integer
from sage.rings.complex_arb import CBF, ComplexBallField
from sage.rings.real_arb import RBF, RealBallField
from sage.structure.sage_object import SageObject

from ore_algebra.analytic.local_solutions import *
from ore_algebra.analytic.safe_cmp import *
from ore_algebra.analytic.utilities import *

logger = logging.getLogger(__name__)

IR, IC = RBF, CBF # TBI
QQi = number_field.QuadraticField(-1, 'i')

######################################################################
# Points
######################################################################

# Main class hierarchy for points:
#
#     Point > RegularPoint > OrdinaryPoint
#
# Auxiliary classes, for classification purposes: RegularSingularPoint,
# IrregularSingularPoint.
#
# (Algorithms for, say, regular singular points should typically work for
# ordinary points as well even when a more specialized version exists. One could
# have QuasiRegularPoints too, but combined with SingularPoints that would make
# the whole thing too complicated.)
#
# TODO: simplify this complicated designed that turned out not to be useful

class Point(SageObject):
    r"""
    A point on the complex plane, in relation with a differential operator.

    Though a differential operator is part of the definition of an instance,
    this class represents a point on the complex plane, not on the Riemann
    surface of the operator.

    A point can be exact (a number field element) or inexact (a real or complex
    interval or ball).

    It can be classified as ordinary, regular singular, etc.

    NOTES:

    - Decouple pure complex points from things that depend on the operator?
    """

    def __init__(self, point, dop=None):
        """
        TESTS::

            sage: from ore_algebra.analytic.ui import *
            sage: from ore_algebra.analytic.path import Point
            sage: Dops, x, Dx = Diffops()
            sage: [Point(z, Dx)
            ....:  for z in [1, 1/2, 1+I, QQbar(I), RIF(1/3), CIF(1/3), pi]]
            [1, 1/2, I + 1, I, [0.333333333333333...], [0.333333333333333...],
            3.141592653589794?]
        """
        SageObject.__init__(self)

        from sage.rings.real_mpfr import RealField_class
        from sage.rings.complex_field import ComplexField_class
        from sage.rings.real_mpfi import RealIntervalField_class
        from sage.rings.complex_interval_field import ComplexIntervalField_class
        try:
            parent = point.parent()
        except AttributeError:
            raise TypeError("unexpected value for point: " + repr(point))
        if isinstance(point, Point):
            self.value = point.value
        elif isinstance(parent, (
                number_field_base.NumberField,
                RealBallField, ComplexBallField)):
            self.value = point
        elif QQ.has_coerce_map_from(parent):
            self.value = QQ.coerce(point)
        # must come before QQbar, due to a bogus coerce map (#14485)
        elif parent is sage.symbolic.ring.SR:
            try:
                return self.__init__(point.pyobject(), dop)
            except TypeError:
                pass
            try:
                self.value = RLF(point)
            except TypeError:
                self.value = CLF(point)
        elif QQbar.has_coerce_map_from(parent):
            alg = QQbar.coerce(point)
            NF, val, hom = alg.as_number_field_element()
            embNF = number_field.NumberField(NF.polynomial(),
                                             NF.variable_name(),
                                             embedding=hom(NF.gen()))
            self.value = val.polynomial()(embNF.gen())
        elif isinstance(parent, (RealField_class, RealIntervalField_class)):
            self.value = RealBallField(point.prec())(point)
        elif isinstance(parent, (ComplexField_class,
                                 ComplexIntervalField_class)):
            self.value = ComplexBallField(point.prec())(point)
        else:
            try:
                self.value = RLF.coerce(point)
            except TypeError:
                self.value = CLF.coerce(point)

        self.dop = dop or point.dop

        self.keep_value = False

    def _repr_(self):
        """
        TESTS::

            sage: from ore_algebra.analytic.ui import *
            sage: from ore_algebra.analytic.path import Point
            sage: Dops, x, Dx = Diffops()
            sage: Point(10**20, Dx)
            ~1.0000e20
        """
        try:
            len = (self.value.numerator().real().numerator().nbits() +
                   self.value.numerator().imag().numerator().nbits() +
                   self.value.denominator().nbits())
            if len > 50:
                return '~' + repr(self.value.n(digits=5))
        except AttributeError:
            pass
        return repr(self.value)

    def descr(self):
        return self._repr_()

    # Numeric representations

    @cached_method
    def iv(self):
        """
        sage: from ore_algebra.analytic.ui import *
        sage: from ore_algebra.analytic.path import Point
        sage: Dops, x, Dx = Diffops()
        sage: [Point(z, Dx).iv()
        ....: for z in [1, 1/2, 1+I, QQbar(I), RIF(1/3), CIF(1/3), pi]]
        [1.000000000000000,
        0.5000000000000000,
        1.000000000000000 + 1.000000000000000*I,
        1.000000000000000*I,
        [0.333333333333333 +/- 3.99e-16],
        [0.333333333333333 +/- 3.99e-16],
        [3.141592653589793 +/- 7.83e-16]]
        """
        return IC(self.value)

    def exact(self):
        r"""
        sage: from ore_algebra.analytic.ui import *
        sage: from ore_algebra.analytic.path import Point
        sage: Dops, x, Dx = Diffops()
        sage: QQi.<i> = QuadraticField(-1)
        sage: [Point(z, Dx).exact() for z in [1, 1/2, 1+i, QQbar(I)]]
        [1, 1/2, i + 1, I]
        sage: Point(RIF(1/3), Dx).exact()
        Traceback (most recent call last):
        ...
        ValueError
        """
        if self.is_exact():
            return self
        raise ValueError

    def is_real(self):
        return RIF.has_coerce_map_from(self.value.parent())

    def is_exact(self):
        return isinstance(self.value,
                (rings.Integer, rings.Rational, rings.NumberFieldElement))

    ### Methods that depend on dop

    def dist_to_sing(self):
        """
        Distance of self to the singularities of self.dop *other than self*.

        TESTS::

            sage: from ore_algebra.analytic.ui import *
            sage: from ore_algebra.analytic.path import Point
            sage: Dops, x, Dx = Diffops()
            sage: dop = (x^2 + 1)*Dx^2 + 2*x*Dx
            sage: Point(1, dop).dist_to_sing()
            [1.41421356237309...]
            sage: Point(i, dop).dist_to_sing()
            2.00...
            sage: Point(1+i, dop).dist_to_sing()
            1.00...

        """
        # TODO - solve over CBF directly; perhaps with arb's own poly solver
        sing = dop_singularities(self.dop, CIF)
        sing = [IC(s) for s in sing]
        close, distant = split(lambda s: s.overlaps(self.iv()), sing)
        if (len(close) >= 2 or len(close) == 1 and
                not self.dop.leading_coefficient()(self.value).is_zero()):
            raise NotImplementedError # refine?
        dist = [(self.iv() - s).abs() for s in distant]
        min_dist = IR(rings.infinity).min(*dist)
        if min_dist.contains_zero():
            raise NotImplementedError # refine???
        return IR(min_dist.lower())

    def local_diffop(self): # ?
        Pols_dop = self.dop.base_ring()
        # NOTE: pushout(QQ[x], K) doesn't handle embeddings well, and creates
        # an L equal but not identical to K. But then other constructors like
        # PolynomialRing(L, x) sometimes return objects over K found in cache,
        # leading to endless headaches with slow coercions. But the version here
        # may be closer to what I really want in any case.
        # XXX: This seems to work in the usual trivial case where we are looking
        # for a scalar domain containing QQ and QQ[i], but probably won't be
        # enough if we really have two different number fields with embeddings
        Scalars = pushout.pushout(Pols_dop.base_ring(), self.value.parent())
        Pols = Pols_dop.change_ring(Scalars)
        A, B = self.dop.base_ring().base_ring(), self.value.parent()
        C = Pols.base_ring()
        assert C is A or C != A
        assert C is B or C != B
        dop_P = self.dop.change_ring(Pols)
        return dop_P.annihilator_of_composition(Pols([self.value, 1]))

    def classify(self):
        r"""
        EXAMPLES::

            sage: from ore_algebra.analytic.ui import *
            sage: from ore_algebra.analytic.path import Point
            sage: Dops, x, Dx = Diffops()

            sage: dop = (x^2 + 1)*Dx^2 + 2*x*Dx
            sage: type(Point(1, dop).classify())
            <class 'ore_algebra.analytic.path.OrdinaryPoint'>
            sage: type(Point(i, dop).classify())
            <class 'ore_algebra.analytic.path.RegularSingularPoint'>
            sage: type(Point(0, x^2*Dx + 1).classify())
            <class 'ore_algebra.analytic.path.IrregularSingularPoint'>

        TESTS::

            sage: type(Point(CIF(1/3), x^2*Dx + 1).classify())
            <class 'ore_algebra.analytic.path.OrdinaryPoint'>
            sage: type(Point(CIF(1/3)-1/3, x^2*Dx + 1).classify())
            <class 'ore_algebra.analytic.path.Point'>
        """
        if self.value.parent().is_exact():
            if self.dop.leading_coefficient()(self.value):
                return OrdinaryPoint(self)
            # Fuchs criterion
            Pols = self.dop.base_ring().change_ring(self.value.parent())
            def val(pol):
                return Pols(pol).valuation(Pols([self.value, -1]))
            ref = val(self.dop.leading_coefficient()) - self.dop.order()
            if all(val(coef) - k >= ref
                   for k, coef in enumerate(self.dop)):
                return RegularSingularPoint(self)
            else:
                return IrregularSingularPoint(self)
        else:
            val = self.dop.leading_coefficient()(self.value)
            try:
                if not val.contains_zero():
                    return OrdinaryPoint(self)
            except AttributeError:
                pass
        return self

class RegularPoint(Point):

    def connect_to_ordinary(self):
        raise NotImplementedError

    def local_basis_structure(self):
        r"""
        EXAMPLES::

            sage: from ore_algebra.analytic.ui import *
            sage: Dops, x, Dx = Diffops()
            sage: Point(0, x*Dx^2 + Dx + x).classify().local_basis_structure()
            [FundamentalSolution(valuation=0, log_power=1, value=None),
             FundamentalSolution(valuation=0, log_power=0, value=None)]
            sage: Point(0, Dx^3 + x*Dx + x).classify().local_basis_structure()
            [FundamentalSolution(valuation=0, log_power=0, value=None),
             FundamentalSolution(valuation=1, log_power=0, value=None),
             FundamentalSolution(valuation=2, log_power=0, value=None)]
        """
        # TODO: provide a way to compute the first terms of the series. First
        # need a good way to share code with fundamental_matrix_regular. Or
        # perhaps modify generalized_series_solutions() to agree with our
        # definition of the basis?
        ldop = self.local_diffop()
        x = ldop.base_ring().gen()
        roots = ldop.indicial_polynomial(x).roots(QQbar)
        sols = [FundamentalSolution(expo, Integer(log_power), None)
                for expo, mult in roots
                for log_power in xrange(mult)]
        sols.sort(key=sort_key_by_asympt)
        return sols

class OrdinaryPoint(RegularPoint):
    pass

class RegularSingularPoint(RegularPoint):

    def descr(self):
        return "regular singular point " + self._repr_()

class IrregularSingularPoint(Point):

    def descr(self):
        return "irregular singular point " + self._repr_()

######################################################################
# Paths
######################################################################

# XXX: do we need special *Steps* (instead of or in addition to special Points)
# for connections to singular points?
class Step(SageObject):
    r"""
    EXAMPLES::

        sage: from ore_algebra.analytic.ui import *
        sage: from ore_algebra.analytic.path import Point, Step
        sage: QQi.<i> = QuadraticField(-1)
        sage: Dops, x, Dx = Diffops()

        sage: s1 = Step(Point(0, x*Dx-1), Point(i/7, x*Dx-1))
        sage: s2 = Step(Point(RIF(1/3), x*Dx-1), Point(pi, x*Dx-1))
        sage: s3 = Step(Point(-i, x*Dx-1), Point(i, x*Dx-1))

        sage: s1, s2
        (0 --> 1/7*i, [0.333333333333333 +/- 3.99e-16] --> 3.141592653589794?)

        sage: list(s1), list(s2)
        ([0, 1/7*i], [[0.333333333333333 +/- 3.99e-16], 3.141592653589794?])

        sage: s1.is_exact(), s2.is_exact()
        (True, False)

        sage: s1.delta(), s2.delta()
        (1/7*i, [2.80825932025646 +/- 1.56e-15])

        sage: s1.length(), s2.length()
        ([0.142857142857142...], [2.8082593202564...])

        sage: s1.check_singularity()
        sage: s2.check_singularity()
        sage: s3.check_singularity()
        Traceback (most recent call last):
        ...
        ValueError: Step -i --> i passes through or too close to singular point
        0 (to compute the connection to a singular point, make it a vertex of
        the path)

        sage: s2.check_convergence()
        Traceback (most recent call last):
        ...
        ValueError: Step ... escapes from the disk of (guaranteed)
        convergence of the solutions at ...

        sage: s2.plot()
        Graphics object consisting of 1 graphics primitive
    """

    def __init__(self, start, end):
        if not (isinstance(start, Point) and isinstance(end, Point)):
            raise TypeError
        if start.dop != end.dop:
            raise ValueError
        self.start = start
        self.end = end

    def _repr_(self):
        return repr(self.start) + " --> " + repr(self.end)

    def __getitem__(self, i):
        if i == 0:
            return self.start
        elif i == 1:
            return self.end
        else:
            raise IndexError

    def is_exact(self):
        return self.start.is_exact() and self.end.is_exact()

    def delta(self):
        return self.end.value - self.start.value

    def length(self):
        return IC(self.delta()).abs()

    def check_singularity(self):
        r"""
        Raise an error if this step goes through a singular point or seems to do
        so at our working precision.

        TESTS::

            sage: from ore_algebra.analytic.ui import *
            sage: from ore_algebra.analytic.path import Point, Step
            sage: Dops, x, Dx = Diffops(); i = QuadraticField(-1, 'i').gen()
            sage: dop = (x^2 + 1)*Dx
            sage: Step(Point(0, dop), Point(0, dop)).check_singularity()
            sage: Step(Point(0, dop), Point(1, dop)).check_singularity()
            sage: Step(Point(1, dop), Point(1, dop)).check_singularity()
            sage: Step(Point(1, dop), Point(i, dop)).check_singularity()
            sage: Step(Point(i, dop), Point(0, dop)).check_singularity()
            sage: Step(Point(i, dop), Point(i, dop)).check_singularity()
            sage: Step(Point(2*i+1, dop), Point(-11/10, dop)).check_singularity()
            sage: Step(Point(2*i, dop), Point(0, dop)).check_singularity()
            Traceback (most recent call last):
            ...
            ValueError: Step 2*i --> 0 passes through or too close to singular
            point 1*I (to compute the connection to a singular point, make it a
            vertex of the path)
            sage: Step(Point(2*i+1, dop), Point(-1, dop)).check_singularity()
            Traceback (most recent call last):
            ...
            ValueError: Step 2*i + 1 --> -1 passes through or too close to
            singular point 1*I (to compute the connection to a singular point,
            make it a vertex of the path)
        """
        dop = self.start.dop
        # TODO: solve over CBF directly?
        sing = [IC(s) for s in dop_singularities(dop, CIF)
                      if s != self.start.value and s != self.end.value]
        for s in sing:
            ds = s - self.start.iv()
            t = self.delta()/ds
            if (ds.contains_zero() or t.imag().contains_zero()
                    and not safe_lt(t.real(), IR.one())):
                raise ValueError(
                    "Step {} passes through or too close to singular point {} "
                    "(to compute the connection to a singular point, make it "
                    "a vertex of the path)"
                    .format(self, sing_as_alg(dop, s)))

    def check_convergence(self):
        r"""
        TESTS::

            sage: from ore_algebra.analytic.ui import *
            sage: from ore_algebra.analytic.path import *
            sage: Dops, x, Dx = Diffops()

            sage: Path([0, 1], x*(x^2+1)*Dx, classify=True).check_convergence()
            Traceback (most recent call last):
            ...
            ValueError: Step 0 --> 1 escapes from the disk of (guaranteed)
            convergence of the solutions at regular singular point 0

            sage: Path([1, 0], x*(x^2+1)*Dx, classify=True).check_convergence()
            Traceback (most recent call last):
            ...
            ValueError: Step 1 --> 0 escapes from the disk of (guaranteed)
            convergence of the solutions at regular singular point 0
        """
        ref = (self.end if isinstance(self.end, RegularSingularPoint)
               else self.start)
        if self.length() >= ref.dist_to_sing(): # not < ?
            raise ValueError("Step {} escapes from the disk of (guaranteed) "
                    "convergence of the solutions at {}"
                    .format(self, ref.descr()))

    def plot(self):
        return plot.arrow2d(self.start.iv().mid(), self.end.iv().mid())

class Path(SageObject):
    """
    A path in ℂ or on the Riemann surface of some operator.

    Note that paths are not the only potentially interesting analytic
    continuation plans: we may reuse already computed transition matrices!

    EXAMPLES::

        sage: from ore_algebra.analytic.ui import *
        sage: from ore_algebra.analytic.path import Path
        sage: Dops, x, Dx = Diffops()
        sage: dop = (x^2 + 1)*Dx^2 + 2*x*Dx

        sage: path = Path([0, 1+I, CBF(2*I)], dop)
        sage: path
        0 --> I + 1 --> 2.000...*I
        sage: path[0]
        0 --> I + 1
        sage: path.vert[0]
        0
        sage: len(path)
        2
        sage: path.dop
        (x^2 + 1)*Dx^2 + 2*x*Dx

        sage: path.check_singularity()
        sage: path.check_convergence()
        Traceback (most recent call last):
        ...
        ValueError: Step 0 --> I + 1 escapes from the disk of (guaranteed)
        convergence of the solutions at 0
    """

    def __init__(self, vert, dop, classify=False):
        r"""
        TESTS::

            sage: from ore_algebra.analytic.ui import *
            sage: from ore_algebra.analytic.path import Path
            sage: Dops, x, Dx = Diffops()
            sage: dop = (x^2 + 1)*Dx^2 + 2*x*Dx

            sage: Path([], Dx)
            Traceback (most recent call last):
            ...
            ValueError: empty path
        """
        SageObject.__init__(self)
        self.dop = dop
        if not vert:
            raise ValueError("empty path")
        self.vert = [v if isinstance(v, Point) else Point(v, dop)
                     for v in vert]
        if classify:
            self.vert = [v.classify() for v in self.vert]

    def __getitem__(self, i):
        r"""
        Return the i-th step of self
        """
        if len(self.vert) < 2:
            raise IndexError
        else:
            return Step(self.vert[i], self.vert[i+1])

    def __len__(self):
        return len(self.vert) - 1

    def _repr_(self):
        return " --> ".join(str(v) for v in self.vert)

    def short_repr(self):
        arrow = " --> " if len(self.vert) < 2 else " --> ... --> "
        return repr(self.vert[0]) + arrow + repr(self.vert[-1])

    def plot(self, disks=False):
        gr  = plot.point2d(dop_singularities(self.dop, CC),
                           marker='*', size=200, color='red')
        for step in self:
            gr += step.plot()
        gr.set_aspect_ratio(1)
        if disks:
            for step in self:
                z = step.start.iv().mid()
                gr += plot.circle((z.real(), z.imag()),
                                  step.start.dist_to_sing().lower(),
                                  linestyle='dotted', color='red')
                gr += plot.circle((z.real(), z.imag()),
                                  step.length().lower(),
                                  linestyle='dashed')
        return gr

    def check_singularity(self):
        """
        EXAMPLES::

            sage: from ore_algebra.analytic.ui import *
            sage: from ore_algebra.analytic.path import Path
            sage: Dops, x, Dx = Diffops()
            sage: QQi.<i> = QuadraticField(-1, 'i')
            sage: dop = (x^2 + 1)*Dx^2 + 2*x*Dx

            sage: Path([0], dop).check_singularity()
            sage: Path([1,3], dop).check_singularity()
            sage: Path([0, i], dop).check_singularity()

            sage: Path([42, 1+i/2, -1+3*i/2], dop).check_singularity()
            Traceback (most recent call last):
            ...
            ValueError: Step 1/2*i + 1 --> 3/2*i - 1 passes through or too close
            to singular point 1*I (to compute the connection to a singular
            point, make it a vertex of the path)

        TESTS:

        Check that we detect additional singular points on path segments with
        regular singular endpoints. Adapted from a NumGfun bug found by
        Christoph Koutschan. ::

            sage: transition_matrix((-8*x^3+4*x^4+5*x^2-x)*Dx
            ....:                   + 10*x^2-4*x-8*x^3+1, [0,1])
            Traceback (most recent call last):
            ...
            ValueError: ...
        """
        for step in self:
            step.check_singularity()

    def check_convergence(self):
        """
        EXAMPLES::

            sage: from ore_algebra.analytic.ui import *
            sage: from ore_algebra.analytic.path import Path
            sage: Dops, x, Dx = Diffops()
            sage: dop = (x^2 + 1)*Dx^2 + 2*x*Dx
            sage: Path([0, 1], dop).check_convergence()
            Traceback (most recent call last):
            ...
            ValueError: Step 0 --> 1 escapes from the disk of (guaranteed)
            convergence of the solutions at 0
            sage: Path([1, 0], dop).check_convergence()
        """
        for step in self:
            step.check_convergence()

    # Path rewriting

    def subdivide(self, threshold=IR(0.6), factor=IR(0.5)):
        # TODO:
        # - support paths passing very close to singular points
        from sage.rings.real_mpfi import RealIntervalField
        new = [self.vert[0]]
        i = 1
        while i < len(self.vert):
            cur, next = new[-1], self.vert[i]
            rad = cur.dist_to_sing()
            dist_to_next = (next.iv() - cur.iv()).abs()
            if (dist_to_next <= threshold*rad if isinstance(next, OrdinaryPoint)
                else (cur.value == next.value
                      or isinstance(cur, OrdinaryPoint)
                         and dist_to_next <= threshold*next.dist_to_sing())):
                new.append(next)
                i += 1
            else:
                dir = (next.iv() - cur.iv())/dist_to_next
                interm = cur.iv() + factor*rad*dir
                is_real = interm.imag().is_zero()
                interm = interm.add_error(rad/8)
                Step(cur, Point(interm, self.dop)).check_singularity() # TBI
                my_RIF = RealIntervalField(interm.real().parent().precision())
                if is_real:
                    interm = my_RIF(interm.real()).simplest_rational()
                else:
                    interm = QQi([my_RIF(interm.real()).simplest_rational(),
                                  my_RIF(interm.imag()).simplest_rational()])
                new.append(OrdinaryPoint(interm, self.dop))
                logger.debug("subdividing %s -> %s", cur, next)
        new = Path(new, self.dop)
        return new

    def find_loops(self): # ???
        raise NotImplementedError

    def optimize_by_homotopy(self):
        raise NotImplementedError

    def remove_duplicates(self):
        raise NotImplementedError

    def bit_burst(self, z0, z1):
        raise NotImplementedError

    def connect_sing(self, XXX): # ???
        raise NotImplementedError

def local_monodromy_path(sing):
    raise NotImplementedError
