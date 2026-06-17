pub trait IterScan: Sized {
    type Output;
    fn scan<'a, I: Iterator<Item = &'a str>>(iter: &mut I) -> Option<Self::Output>;
}
pub trait MarkedIterScan: Sized {
    type Output;
    fn mscan<'a, I: Iterator<Item = &'a str>>(self, iter: &mut I) -> Option<Self::Output>;
}
#[derive(Debug)]
pub struct Scanner<'a> {
    iter: std::str::SplitAsciiWhitespace<'a>,
}
impl<'a> Scanner<'a> {
    #[inline]
    pub fn new(s: &'a str) -> Self {
        let iter = s.split_ascii_whitespace();
        Self { iter }
    }
    #[inline]
    pub fn scan<T: IterScan>(&mut self) -> <T as IterScan>::Output {
        T::scan(&mut self.iter).unwrap()
    }
    #[inline]
    pub fn mscan<T: MarkedIterScan>(&mut self, marker: T) -> <T as MarkedIterScan>::Output {
        marker.mscan(&mut self.iter).unwrap()
    }
    #[inline]
    pub fn scan_vec<T: IterScan>(&mut self, size: usize) -> Vec<<T as IterScan>::Output> {
        (0..size)
            .map(|_| T::scan(&mut self.iter).unwrap())
            .collect()
    }
    #[inline]
    pub fn scan_chars(&mut self) -> Vec<char> {
        self.iter.next().unwrap().chars().collect::<Vec<char>>()
    }
}
mod scanner_impls {
    use super::*;
    macro_rules !iter_scan_impls {($($t :ty ) *) =>{$(impl IterScan for $t {type Output =Self ;#[inline ] fn scan <'a ,I :Iterator <Item =&'a str >>(iter :&mut I ) ->Option <Self >{iter .next () ?.parse ::<$t >() .ok () } } ) *} ;}
    iter_scan_impls !(char u8 u16 u32 u64 usize i8 i16 i32 i64 isize f32 f64 u128 i128 String ) ;
    macro_rules !iter_scan_tuple_impl {($($T :ident ) *) =>{impl <$($T :IterScan ) ,*>IterScan for ($($T ,) *) {type Output =($(<$T as IterScan >::Output ,) *) ;#[inline ] fn scan <'a ,It :Iterator <Item =&'a str >>(_iter :&mut It ) ->Option <Self ::Output >{Some (($($T ::scan (_iter ) ?,) *) ) } } } ;}
    iter_scan_tuple_impl!();
    iter_scan_tuple_impl!(A);
    iter_scan_tuple_impl !(A B ) ;
    iter_scan_tuple_impl !(A B C ) ;
    iter_scan_tuple_impl !(A B C D ) ;
    iter_scan_tuple_impl !(A B C D E ) ;
    iter_scan_tuple_impl !(A B C D E F ) ;
    iter_scan_tuple_impl !(A B C D E F G ) ;
    iter_scan_tuple_impl !(A B C D E F G H ) ;
    iter_scan_tuple_impl !(A B C D E F G H I ) ;
    iter_scan_tuple_impl !(A B C D E F G H I J ) ;
    iter_scan_tuple_impl !(A B C D E F G H I J K ) ;
    pub struct ScannerIter<'a, 'b, T> {
        inner: &'b mut Scanner<'a>,
        _marker: std::marker::PhantomData<fn() -> T>,
    }
    impl<'a, 'b, T: IterScan> Iterator for ScannerIter<'a, 'b, T> {
        type Item = <T as IterScan>::Output;
        fn next(&mut self) -> Option<Self::Item> {
            T::scan(&mut self.inner.iter)
        }
    }
    impl<'a> Scanner<'a> {
        #[inline]
        pub fn iter<'b, T: IterScan>(&'b mut self) -> ScannerIter<'a, 'b, T> {
            ScannerIter {
                inner: self,
                _marker: std::marker::PhantomData,
            }
        }
    }
}
mod marker {
    use super::*;
    pub struct Usize1;
    impl IterScan for Usize1 {
        type Output = usize;
        #[inline]
        fn scan<'a, I: Iterator<Item = &'a str>>(iter: &mut I) -> Option<Self::Output> {
            usize::scan(iter).map(|x| x.wrapping_sub(1))
        }
    }
    pub struct Isize1;
    impl IterScan for Isize1 {
        type Output = isize;
        #[inline]
        fn scan<'a, I: Iterator<Item = &'a str>>(iter: &mut I) -> Option<Self::Output> {
            isize::scan(iter).map(|x| x.wrapping_sub(1))
        }
    }
}
#[macro_export]
macro_rules !min {($e :expr ) =>{$e } ;($e :expr ,$($es :expr ) ,+) =>{std ::cmp ::min ($e ,min !($($es ) ,+) ) } ;}
#[macro_export]
macro_rules !chmin {($dst :expr ,$($src :expr ) ,+) =>{{let x =std ::cmp ::min ($dst ,min !($($src ) ,+) ) ;$dst =x ;} } ;}
#[macro_export]
macro_rules !max {($e :expr ) =>{$e } ;($e :expr ,$($es :expr ) ,+) =>{std ::cmp ::max ($e ,max !($($es ) ,+) ) } ;}
#[macro_export]
macro_rules !chmax {($dst :expr ,$($src :expr ) ,+) =>{{let x =std ::cmp ::max ($dst ,max !($($src ) ,+) ) ;$dst =x ;} } ;}
use std::collections::HashMap;
#[derive(Clone, Debug)]
pub struct UnionFind {
    parents: Vec<isize>,
}
impl UnionFind {
    pub fn new(n: usize) -> Self {
        let parents = vec![-1; n];
        Self { parents }
    }
    pub fn find(&mut self, x: usize) -> usize {
        if self.parents[x] < 0 {
            x
        } else {
            let xx = self.parents[x] as usize;
            let y = self.find(xx);
            self.parents[x] = y as isize;
            y
        }
    }
    pub fn unite(&mut self, x: usize, y: usize) -> bool {
        use std::mem::swap;
        let mut x = self.find(x);
        let mut y = self.find(y);
        if x == y {
            return false;
        }
        if self.parents[x] > self.parents[y] {
            swap(&mut x, &mut y);
        }
        self.parents[x] += self.parents[y];
        self.parents[y] = x as isize;
        true
    }
    pub fn unite_light(&mut self, x: usize, y: usize) -> bool {
        let x = self.find(x);
        let y = self.find(y);
        if x == y {
            return false;
        }
        self.parents[x] += self.parents[y];
        self.parents[y] = x as isize;
        true
    }
    pub fn size(&mut self, x: usize) -> usize {
        let x = self.find(x);
        (-self.parents[x]) as usize
    }
    pub fn same(&mut self, x: usize, y: usize) -> bool {
        self.find(x) == self.find(y)
    }
    pub fn members(&mut self, x: usize) -> Vec<usize> {
        let root = self.find(x);
        (0..self.parents.len())
            .filter(|i| self.find(*i) == root)
            .collect::<Vec<usize>>()
    }
    pub fn roots(&mut self) -> Vec<usize> {
        (0..self.parents.len())
            .filter(|i| self.parents[*i] < 0)
            .collect::<Vec<usize>>()
    }
    pub fn all_group_members(&mut self) -> HashMap<usize, Vec<usize>> {
        let mut groups_map = HashMap::new();
        for x in 0..self.parents.len() {
            let r = self.find(x);
            groups_map.entry(r).or_insert(vec![]).push(x);
        }
        groups_map
    }
}
fn main() {
    #[allow(unused_imports)]
    use std::io::{Read as _, Write as _};
    let __out = std::io::stdout();
    let mut __in_buf = String::new();
    std::io::stdin().read_to_string(&mut __in_buf).unwrap();
    let mut __scanner = Scanner::new(&__in_buf);
    #[allow(unused_macros)]
    macro_rules !scan {() =>{scan !(usize ) } ;(($($t :tt ) ,*) ) =>{($(scan !($t ) ) ,*) } ;([$t :tt ;$len :expr ] ) =>{(0 ..$len ) .map (|_ |scan !($t ) ) .collect ::<Vec <_ >>() } ;({$t :tt =>$f :expr } ) =>{$f (scan !($t ) ) } ;(chars ) =>{__scanner .scan_chars () } ;($t :ty ) =>{__scanner .scan ::<$t >() } ;}
    let mut __out = std::io::BufWriter::new(__out.lock());
    #[allow(unused_macros)]
    macro_rules !print {($($arg :tt ) *) =>(::std ::write !(__out ,$($arg ) *) .unwrap () ) }
    #[allow(unused_macros)]
    macro_rules !println {($($arg :tt ) *) =>(::std ::writeln !(__out ,$($arg ) *) .unwrap () ) }
    #[allow(unused_macros)]
    macro_rules! echo {
        ($iter :expr ) => {
            echo!($iter, "\n")
        };
        ($iter :expr ,$sep :expr ) => {
            let mut iter = $iter;
            if let Some(item) = iter.next() {
                print!("{}", item);
            }
            for item in iter {
                print!("{}{}", $sep, item);
            }
            println!();
        };
    }
    let n = scan!();
    let m = scan!();
    let ab = scan!([(marker::Usize1, marker::Usize1); m]);
    let mut deg = vec![0; n];
    for &(a, b) in &ab {
        deg[a] += 1;
        deg[b] += 1;
    }
    let mut ans = deg.iter().all(|d| d % 2 == 0);
    if ans && !deg.iter().any(|&d| d >= 6) {
        let d4: Vec<_> = (0..n).filter(|&u| deg[u] == 4).collect();
        if d4.len() == 2 {
            let (x, y) = (d4[0], d4[1]);
            let mut uf = UnionFind::new(n);
            let mut ok = false;
            for &(a, b) in &ab {
                if !(uf.same(x, a) && uf.same(y, b) || uf.same(y, a) && uf.same(x, b)) {
                    if !uf.unite(a, b) {
                        ok = true;
                    }
                }
            }
            ans = ok;
        } else if d4.len() < 2 {
            ans = false;
        }
    }
    println!("{}", if ans { "Yes" } else { "No" });
}