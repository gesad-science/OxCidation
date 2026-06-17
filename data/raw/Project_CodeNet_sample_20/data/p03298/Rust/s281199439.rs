pub trait Zero: PartialEq + Sized {
    fn zero() -> Self;
    #[inline]
    fn is_zero(&self) -> bool {
        self == &Self::zero()
    }
}
pub trait One: PartialEq + Sized {
    fn one() -> Self;
    #[inline]
    fn is_one(&self) -> bool {
        self == &Self::one()
    }
}
macro_rules !zero_one_impls {($({$Trait :ident $method :ident $($t :ty ) *,$e :expr } ) *) =>{$($(impl $Trait for $t {#[inline ] fn $method () ->Self {$e } } ) *) *} ;}
zero_one_impls !({Zero zero u8 u16 u32 u64 usize i8 i16 i32 i64 isize u128 i128 ,0 } {Zero zero f32 f64 ,0. } {One one u8 u16 u32 u64 usize i8 i16 i32 i64 isize u128 i128 ,1 } {One one f32 f64 ,1. } ) ;
pub trait IterScan: Sized {
    type Output;
    fn scan<'a, I: Iterator<Item = &'a str>>(iter: &mut I) -> Option<Self::Output>;
}
pub trait MarkedIterScan: Sized {
    type Output;
    fn mscan<'a, I: Iterator<Item = &'a str>>(self, iter: &mut I) -> Option<Self::Output>;
}
#[derive(Clone, Debug)]
pub struct Scanner<'a> {
    iter: std::str::SplitAsciiWhitespace<'a>,
}
mod scanner_impls {
    use super::*;
    impl<'a> Scanner<'a> {
        #[inline]
        pub fn new(s: &'a str) -> Self {
            let iter = s.split_ascii_whitespace();
            Self { iter }
        }
        #[inline]
        pub fn scan<T: IterScan>(&mut self) -> <T as IterScan>::Output {
            <T as IterScan>::scan(&mut self.iter).expect("scan error")
        }
        #[inline]
        pub fn mscan<T: MarkedIterScan>(&mut self, marker: T) -> <T as MarkedIterScan>::Output {
            marker.mscan(&mut self.iter).expect("scan error")
        }
        #[inline]
        pub fn scan_vec<T: IterScan>(&mut self, size: usize) -> Vec<<T as IterScan>::Output> {
            (0..size)
                .map(|_| <T as IterScan>::scan(&mut self.iter).expect("scan error"))
                .collect()
        }
        #[inline]
        pub fn iter<'b, T: IterScan>(&'b mut self) -> ScannerIter<'a, 'b, T> {
            ScannerIter {
                inner: self,
                _marker: std::marker::PhantomData,
            }
        }
    }
    macro_rules !iter_scan_impls {($($t :ty ) *) =>{$(impl IterScan for $t {type Output =Self ;#[inline ] fn scan <'a ,I :Iterator <Item =&'a str >>(iter :&mut I ) ->Option <Self >{iter .next () ?.parse ::<$t >() .ok () } } ) *} ;}
    iter_scan_impls !(char u8 u16 u32 u64 usize i8 i16 i32 i64 isize f32 f64 u128 i128 String ) ;
    macro_rules !iter_scan_tuple_impl {($($T :ident ) *) =>{impl <$($T :IterScan ) ,*>IterScan for ($($T ,) *) {type Output =($(<$T as IterScan >::Output ,) *) ;#[inline ] fn scan <'a ,It :Iterator <Item =&'a str >>(_iter :&mut It ) ->Option <Self ::Output >{Some (($(<$T as IterScan >::scan (_iter ) ?,) *) ) } } } ;}
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
        #[inline]
        fn next(&mut self) -> Option<Self::Item> {
            <T as IterScan>::scan(&mut self.inner.iter)
        }
    }
}
pub mod marker {
    use super::*;
    use std::{iter::FromIterator, marker::PhantomData};
    #[derive(Debug, Copy, Clone)]
    pub struct Usize1;
    impl IterScan for Usize1 {
        type Output = usize;
        #[inline]
        fn scan<'a, I: Iterator<Item = &'a str>>(iter: &mut I) -> Option<Self::Output> {
            Some(<usize as IterScan>::scan(iter)?.checked_sub(1)?)
        }
    }
    #[derive(Debug, Copy, Clone)]
    pub struct Chars;
    impl IterScan for Chars {
        type Output = Vec<char>;
        #[inline]
        fn scan<'a, I: Iterator<Item = &'a str>>(iter: &mut I) -> Option<Self::Output> {
            Some(iter.next()?.chars().collect())
        }
    }
    #[derive(Debug, Copy, Clone)]
    pub struct CharsWithBase(char);
    impl MarkedIterScan for CharsWithBase {
        type Output = Vec<usize>;
        #[inline]
        fn mscan<'a, I: Iterator<Item = &'a str>>(self, iter: &mut I) -> Option<Self::Output> {
            Some(
                iter.next()?
                    .chars()
                    .map(|c| (c as u8 - self.0 as u8) as usize)
                    .collect(),
            )
        }
    }
    #[derive(Debug, Copy, Clone)]
    pub struct Collect<T: IterScan, B: FromIterator<<T as IterScan>::Output>> {
        size: usize,
        _marker: PhantomData<fn() -> (T, B)>,
    }
    impl<T: IterScan, B: FromIterator<<T as IterScan>::Output>> Collect<T, B> {
        pub fn new(size: usize) -> Self {
            Self {
                size,
                _marker: PhantomData,
            }
        }
    }
    impl<T: IterScan, B: FromIterator<<T as IterScan>::Output>> MarkedIterScan for Collect<T, B> {
        type Output = B;
        #[inline]
        fn mscan<'a, I: Iterator<Item = &'a str>>(self, iter: &mut I) -> Option<Self::Output> {
            Some(
                (0..self.size)
                    .map(|_| <T as IterScan>::scan(iter).expect("scan error"))
                    .collect::<B>(),
            )
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
fn main() {
    #![allow(unused_imports, unused_macros)]
    use std::io::{stdin, stdout, BufWriter, Read as _, Write as _};
    let mut __in_buf = Vec::new();
    stdin().read_to_end(&mut __in_buf).expect("io error");
    let __in_buf = unsafe { String::from_utf8_unchecked(__in_buf) };
    let mut scanner = Scanner::new(&__in_buf);
    macro_rules !scan {() =>{scan !(usize ) } ;(($($t :tt ) ,*) ) =>{($(scan !($t ) ) ,*) } ;([$t :ty ;$len :expr ] ) =>{scanner .scan_vec ::<$t >($len ) } ;([$t :tt ;$len :expr ] ) =>{(0 ..$len ) .map (|_ |scan !($t ) ) .collect ::<Vec <_ >>() } ;({$e :expr } ) =>{scanner .mscan ($e ) } ;($t :ty ) =>{scanner .scan ::<$t >() } ;}
    let __out = stdout();
    let mut __out = BufWriter::new(__out.lock());
    macro_rules !print {($($arg :tt ) *) =>(::std ::write !(__out ,$($arg ) *) .expect ("io error" ) ) }
    macro_rules !println {($($arg :tt ) *) =>(::std ::writeln !(__out ,$($arg ) *) .expect ("io error" ) ) }
    macro_rules! echo {
        ($iter :expr ) => {
            echo!($iter, '\n')
        };
        ($iter :expr ,$sep :expr ) => {
            let mut iter = $iter.into_iter();
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
    let s = scan!(marker::Chars);
    let t = &s[n..].iter().cloned().rev().collect::<Vec<_>>();
    let mut ans = 0;
    let mut mp1 = std::collections::HashMap::<_, usize>::new();
    let mut mp2 = std::collections::HashMap::<_, usize>::new();
    for i in 0..1 << n {
        let mut v1 = vec![vec![]; 2];
        let mut v2 = vec![vec![]; 2];
        for j in 0..n {
            v1[(i & 1 << j != 0) as usize].push(s[j]);
            v2[(i & 1 << j != 0) as usize].push(t[j]);
        }
        *mp1.entry(v1).or_default() += 1usize;
        *mp2.entry(v2).or_default() += 1usize;
    }
    for (k, v) in mp1.iter() {
        ans += mp2.get(k).cloned().unwrap_or_default() * v;
    }
    println!("{}", ans);
}