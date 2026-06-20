"""Warcraft III numeric order-id lookup table."""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

_ORDER_ID_DATA: Final = (
    "851971=smart;851972=stop;851973=stunned;851975=instant3;851976=cancel;851980=setrally;851981=getitem;"
    "851983=attack;851984=attackground;851985=attackonce;851986=move;851987=instant2;851988=aimove;"
    "851990=patrol;851991=instant1;851993=holdposition;851994=build;851995=humanbuild;851996=orcbuild;"
    "851997=nightelfbuild;851998=undeadbuild;851999=resumebuild;852000=skillmenu;852001=dropitem;"
    "852002=moveslot1;852003=moveslot2;852004=moveslot3;852005=moveslot4;852006=moveslot5;852007=moveslot6;"
    "852008=useslot1;852009=useslot2;852010=useslot3;852011=useslot4;852012=useslot5;852013=useslot6;"
    "852015=detectaoe;852017=resumeharvesting;852018=harvest;852019=instant4;852020=returnresources;"
    "852021=autoharvestgold;852022=autoharvestlumber;852023=neutraldetectaoe;852024=repair;852025=repairon;"
    "852026=repairoff;852039=revive;852040=selfdestruct;852041=selfdestructon;852042=selfdestructoff;"
    "852043=board;852044=forceboard;852046=load;852047=unload;852048=unloadall;852049=unloadallinstant;"
    "852050=loadcorpse;852053=loadcorpseinstant;852054=unloadallcorpses;852055=defend;852056=undefend;"
    "852057=dispel;852060=flare;852063=heal;852064=healon;852065=healoff;852066=innerfire;852067=innerfireon;"
    "852068=innerfireoff;852069=invisibility;852071=militiaconvert;852072=militia;852073=militiaoff;"
    "852074=polymorph;852075=slow;852076=slowon;852077=slowoff;852079=tankdroppilot;852080=tankloadpilot;"
    "852081=tankpilot;852082=townbellon;852083=townbelloff;852086=avatar;852087=unavatar;852089=blizzard;"
    "852090=divineshield;852091=undivineshield;852092=holybolt;852093=massteleport;852094=resurrection;"
    "852095=thunderbolt;852096=thunderclap;852097=waterelemental;852099=battleroar;852100=berserk;"
    "852101=bloodlust;852102=bloodluston;852103=bloodlustoff;852104=devour;852105=evileye;852106=ensnare;"
    "852107=ensnareon;852108=ensnareoff;852109=healingward;852110=lightningshield;852111=purge;"
    "852113=standdown;852114=stasistrap;852119=chainlightning;852121=earthquake;852122=farsight;"
    "852123=mirrorimage;852125=shockwave;852126=spiritwolf;852127=stomp;852128=whirlwind;852129=windwalk;"
    "852130=unwindwalk;852131=ambush;852132=autodispel;852133=autodispelon;852134=autodispeloff;"
    "852135=barkskin;852136=barkskinon;852137=barkskinoff;852138=bearform;852139=unbearform;"
    "852140=corrosivebreath;852142=loadarcher;852143=mounthippogryph;852144=cyclone;852145=detonate;"
    "852146=eattree;852147=entangle;852148=entangleinstant;852149=faeriefire;852150=faeriefireon;"
    "852151=faeriefireoff;852155=ravenform;852156=unravenform;852157=recharge;852158=rechargeon;"
    "852159=rechargeoff;852160=rejuvination;852161=renew;852162=renewon;852163=renewoff;852164=roar;"
    "852165=root;852166=unroot;852171=entanglingroots;852173=flamingarrowstarg;852174=flamingarrows;"
    "852175=unflamingarrows;852176=forceofnature;852177=immolation;852178=unimmolation;852179=manaburn;"
    "852180=metamorphosis;852181=scout;852182=sentinel;852183=starfall;852184=tranquility;"
    "852185=acolyteharvest;852186=antimagicshell;852187=blight;852188=cannibalize;852189=cripple;852190=curse;"
    "852191=curseon;852192=curseoff;852195=freezingbreath;852196=possession;852197=raisedead;"
    "852198=raisedeadon;852199=raisedeadoff;852200=instant;852201=requestsacrifice;852202=restoration;"
    "852203=restorationon;852204=restorationoff;852205=sacrifice;852206=stoneform;852207=unstoneform;"
    "852209=unholyfrenzy;852210=unsummon;852211=web;852212=webon;852213=weboff;852214=wispharvest;"
    "852215=auraunholy;852216=auravampiric;852217=animatedead;852218=carrionswarm;852219=darkritual;"
    "852220=darksummoning;852221=deathanddecay;852222=deathcoil;852223=deathpact;852224=dreadlordinferno;"
    "852225=frostarmor;852226=frostnova;852227=sleep;852228=darkconversion;852229=darkportal;"
    "852230=fingerofdeath;852231=firebolt;852232=inferno;852233=gold2lumber;852234=lumber2gold;852235=spies;"
    "852237=rainofchaos;852238=rainoffire;852239=request_hero;852240=disassociate;852241=revenge;"
    "852242=soulpreservation;852243=coldarrowstarg;852244=coldarrows;852245=uncoldarrows;"
    "852246=creepanimatedead;852247=creepdevour;852248=creepheal;852249=creephealon;852250=creephealoff;"
    "852252=creepthunderbolt;852253=creepthunderclap;852254=poisonarrowstarg;852255=poisonarrows;"
    "852256=unpoisonarrows;852283=resurrection;852285=scrollofspeed;852458=frostarmoron;852459=frostarmoroff;"
    "852466=awaken;852467=nagabuild;852469=mount;852470=dismount;852473=cloudoffog;852474=controlmagic;"
    "852478=magicdefense;852479=magicundefense;852480=magicleash;852481=phoenixfire;852482=phoenixmorph;"
    "852483=spellsteal;852484=spellstealon;852485=spellstealoff;852486=banish;852487=drain;852488=flamestrike;"
    "852489=summonphoenix;852490=ancestralspirit;852491=ancestralspirittarget;852493=corporealform;"
    "852494=uncorporealform;852495=disenchant;852496=etherealform;852497=unetherealform;852499=spiritlink;"
    "852500=unstableconcoction;852501=healingwave;852502=hex;852503=voodoo;852504=ward;852505=autoentangle;"
    "852506=autoentangleinstant;852507=coupletarget;852508=coupleinstant;852509=decouple;852511=grabtree;"
    "852512=manaflareon;852513=manaflareoff;852514=phaseshift;852515=phaseshifton;852516=phaseshiftoff;"
    "852517=phaseshiftinstant;852520=taunt;852521=vengeance;852522=vengeanceon;852523=vengeanceoff;"
    "852524=vengeanceinstant;852525=blink;852526=fanofknives;852527=shadowstrike;852528=spiritofvengeance;"
    "852529=absorb;852531=avengerform;852532=unavengerform;852533=burrow;852534=unburrow;852536=devourmagic;"
    "852539=flamingattacktarg;852540=flamingattack;852541=unflamingattack;852542=replenish;852543=replenishon;"
    "852544=replenishoff;852545=replenishlife;852546=replenishlifeon;852547=replenishlifeoff;"
    "852548=replenishmana;852549=replenishmanaon;852550=replenishmanaoff;852551=carrionscarabs;"
    "852552=carrionscarabson;852553=carrionscarabsoff;852554=carrionscarabsinstant;852555=impale;"
    "852556=locustswarm;852560=breathoffrost;852561=frenzy;852562=frenzyon;852563=frenzyoff;"
    "852564=mechanicalcritter;852565=mindrot;852566=neutralinteract;852568=preservation;852569=sanctuary;"
    "852570=shadowsight;852571=spellshield;852572=spellshieldaoe;852573=spirittroll;852574=steal;"
    "852576=attributemodskill;852577=blackarrow;852578=blackarrowon;852579=blackarrowoff;852580=breathoffire;"
    "852581=charm;852583=doom;852585=drunkenhaze;852586=elementalfury;852587=forkedlightning;"
    "852588=howlofterror;852589=manashieldon;852590=manashieldoff;852591=monsoon;852592=silence;"
    "852593=stampede;852594=summongrizzly;852595=summonquillbeast;852596=summonwareagle;852597=tornado;"
    "852598=wateryminion;852599=battleroar;852600=channel;852601=parasite;852602=parasiteon;852603=parasiteoff;"
    "852604=submerge;852605=unsubmerge;852630=neutralspell;852651=militiaunconvert;852652=clusterrockets;"
    "852656=robogoblin;852657=unrobogoblin;852658=summonfactory;852662=acidbomb;852663=chemicalrage;"
    "852664=healingspray;852665=transmute;852667=lavamonster;852668=soulburn;852669=volcano;"
    "852670=incineratearrow;852671=incineratearrowon;852672=incineratearrowoff;"
)


def _parse_order_id_data(data: str) -> dict[str, str]:
    names: dict[str, str] = {}
    for item in data.split(";"):
        if not item:
            continue
        order_id, name = item.split("=", 1)
        names[order_id] = name
    return names


ORDER_ID_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    _parse_order_id_data(_ORDER_ID_DATA),
)


def order_name_from_id(order_id: str) -> str:
    """Return the canonical order name, preserving unknown numeric ids."""
    return ORDER_ID_NAMES.get(order_id, f"id:{order_id}")
