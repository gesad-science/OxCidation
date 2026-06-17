#include <stdio.h>
#define ll long long
#define rep(i,l,r)for(ll i=(l);i<(r);i++)
#define max(p,q)((p)>(q)?(p):(q))

int main(){
	ll n,m;
	while(scanf("%lld%lld",&n,&m),n){
		ll x[110]={};
		rep(_,0,n){
			ll d,v;
			scanf("%lld%lld",&d,&v);
			x[d]=max(x[d],v);
		}
		ll ans=0;
		rep(i,1,m+1)ans+=x[i];
		printf("%lld\n",ans);
	}
}
